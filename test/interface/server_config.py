#!/usr/bin/env python
# Copyright 2014 RethinkDB, all rights reserved.

from __future__ import print_function

import os, sys, time

startTime = time.time()

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, 'common')))
import driver, scenario_common, utils, vcoptparse

op = vcoptparse.OptParser()
scenario_common.prepare_option_parser_mode_flags(op)
_, command_prefix, serve_options = scenario_common.parse_mode_flags(op.parse(sys.argv))

r = utils.import_python_driver()
dbName, tableName = utils.get_test_db_table()

print("Starting cluster of %d servers (%.2fs)" % (2, time.time() - startTime))
with driver.Cluster(output_folder='.') as cluster:

    process1 = driver.Process(cluster, files='a', server_tags=["foo"], command_prefix=command_prefix, extra_options=serve_options + ["--cache-size", "auto"])
    process2 = driver.Process(cluster, files='b', server_tags=["foo", "bar"], command_prefix=command_prefix, extra_options=serve_options + ["--cache-size", "123"])
    cluster.wait_until_ready()
    
    print("Establishing ReQL connections (%.2fs)" % (time.time() - startTime))
    
    reql_conn1 = r.connect(process1.host, process1.driver_port)
    reql_conn2 = r.connect(process2.host, process2.driver_port)

    assert r.db("rethinkdb").table("server_config").count().run(reql_conn1) == 2
    assert process1.uuid == r.db("rethinkdb").table("server_config").filter({"name":process1.name}).nth(0)["id"].run(reql_conn1)
    assert process2.uuid == r.db("rethinkdb").table("server_config").filter({"name":"b"}).nth(0)["id"].run(reql_conn1)

    def check_name(uuid, expect_name):
        names = [r.db("rethinkdb").table("server_config").get(uuid)["name"].run(c) for c in [reql_conn1, reql_conn2]]
        assert names[0] == names[1] == expect_name, 'The tags did not match: %s vs. %s vs. %s' % (names[0], names[1], expect_name)
    
    def check_tags(uuid, expect_tags):
        tags = [r.db("rethinkdb").table("server_config").get(uuid)["tags"].run(c) for c in [reql_conn1, reql_conn2]]
        assert set(tags[0]) == set(tags[1]) == set(expect_tags), 'The tags did not match: %s vs. %s vs. %s' % (str(tags[0]), str(tags[1]), str(expect_tags))
    
    # == check working with names
    
    print("Checking initial names (%.2fs)" % (time.time() - startTime))
    check_name(process1.uuid, "a")
    check_name(process2.uuid, "b")
    cluster.check()

    print("Checking changing name locally (%.2fs)" % (time.time() - startTime))
    res = r.db("rethinkdb").table("server_config").get(process1.uuid).update({"name": "a2"}).run(reql_conn1)
    assert res["errors"] == 0
    time.sleep(.2)
    check_name(process1.uuid, "a2")
    check_name(process2.uuid, "b")
    cluster.check()

    print("Checking changing name remotely (%.2fs)" % (time.time() - startTime))
    res = r.db("rethinkdb").table("server_config").get(process2.uuid).update({"name": "b2"}).run(reql_conn1)
    assert res["errors"] == 0
    time.sleep(.2)
    check_name(process1.uuid, "a2")
    check_name(process2.uuid, "b2")
    cluster.check()

    print("Checking that name conflicts are rejected (%.2fs)" % (time.time() - startTime))
    res = r.db("rethinkdb").table("server_config").get(process1.uuid).update({"name": "b2"}).run(reql_conn1)
    assert res["errors"] == 1
    assert "already exists" in res["first_error"]
    time.sleep(.2)
    check_name(process1.uuid, "a2")
    check_name(process2.uuid, "b2")
    cluster.check()

    # == check working with tags

    print("Checking initial tags (%.2fs)" % (time.time() - startTime))
    check_tags(process1.uuid, ["default", "foo"])
    check_tags(process2.uuid, ["default", "foo", "bar"])
    cluster.check()

    print("Checking changing tags locally (%.2fs)" % (time.time() - startTime))
    res = r.db("rethinkdb").table("server_config").get(process1.uuid).update({"tags": ["baz"]}).run(reql_conn1)
    assert res["errors"] == 0
    time.sleep(.2)
    check_tags(process1.uuid, ["baz"])
    check_tags(process2.uuid, ["default", "foo", "bar"])
    cluster.check()

    print("Checking changing tags remotely (%.2fs)" % (time.time() - startTime))
    res = r.db("rethinkdb").table("server_config").get(process2.uuid).update({"tags": ["quz"]}).run(reql_conn1)
    assert res["errors"] == 0
    time.sleep(.2)
    check_tags(process1.uuid, ["baz"])
    check_tags(process2.uuid, ["quz"])
    cluster.check()

    print("Checking that invalid tags are rejected (%.2fs)" % (time.time() - startTime))
    res = r.db("rethinkdb").table("server_config").get(process1.uuid).update({"tags": [":-)"]}).run(reql_conn1)
    assert res["errors"] == 1, "It shouldn't be possible to set tags that aren't valid names."
    time.sleep(.2)
    check_tags(process1.uuid, ["baz"])
    check_tags(process2.uuid, ["quz"])
    cluster.check()

    print("Checking initial cache size (%.2fs)" % (time.time() - startTime))
    res = r.db("rethinkdb").table("server_config").get(process1.uuid)["cache_size_mb"].run(reql_conn1)
    assert res == "auto", res
    res = r.db("rethinkdb").table("server_config") \
           .get(process2.uuid)["cache_size_mb"].run(reql_conn1)
    assert res == 123, res
    res = r.db("rethinkdb").table("server_status") \
           .get(process2.uuid)["process"]["cache_size_mb"].run(reql_conn1)
    assert res == 123, res

    print("Checking that cache size can be changed...")
    res = r.db("rethinkdb").table("server_config") \
           .get(process2.uuid).update({"cache_size_mb": 234}) \
           .run(reql_conn1)
    assert res["errors"] == 0, res
    res = r.db("rethinkdb").table("server_config") \
           .get(process2.uuid)["cache_size_mb"].run(reql_conn1)
    assert res == 234
    res = r.db("rethinkdb").table("server_status") \
           .get(process2.uuid)["process"]["cache_size_mb"].run(reql_conn1)
    assert res == 234, res

    print("Checking that absurd cache sizes are rejected...")
    def try_bad_cache_size(size, message):
        res = r.db("rethinkdb").table("server_config") \
               .get(process2.uuid).update({"cache_size_mb": r.literal(size)}) \
               .run(reql_conn1)
        assert res["errors"] == 1, res
        assert message in res["first_error"]
    try_bad_cache_size("foobar", "wrong format")
    try_bad_cache_size(-30, "wrong format")
    try_bad_cache_size({}, "wrong format")
    # 2**40 is chosen so that it fits into a 64-bit integer when expressed in bytes, to
    # test the code path where the value is sent to the other server but then rejected by
    # validate_total_cache_size().
    try_bad_cache_size(2**40, "Error when trying to change the cache size of server")
    # 2**100 is chosen so that it doesn't fit into a 64-bit integer, so it will take a
    # different code path and get a different error message.
    try_bad_cache_size(2**100, "wrong format")

    print("Checking that nonsense is rejected...")
    res = r.db("rethinkdb").table("server_config") \
           .insert({"name": "hi", "tags": [], "cache_size": 100}).run(reql_conn1)
    assert res["errors"] == 1, res
    res = r.db("rethinkdb").table("server_config").update({"foo": "bar"}).run(reql_conn1)
    assert res["errors"] == 2, res
    res = r.db("rethinkdb").table("server_config").update({"name": 2}).run(reql_conn1)
    assert res["errors"] == 2, res
    res = r.db("rethinkdb").table("server_config").replace(r.row.without("name")) \
           .run(reql_conn1)
    assert res["errors"] == 2, res
    res = r.db("rethinkdb").table("server_config") \
           .update({"cache_size": "big!"}).run(reql_conn1)
    assert res["errors"] == 2, res
    res = r.db("rethinkdb").table("server_config").update({"tags": 0}).run(reql_conn1)
    assert res["errors"] == 2, res

    cluster.check_and_stop()

    print("Cleaning up (%.2fs)" % (time.time() - startTime))
print("Done (%.2fs)" % (time.time() - startTime))
