import logging

from dbgpt.datasource.sql_guard import sql_fingerprint
from dbgpt_ext.datasource.conn_spark import SparkConnector


class _Row:
    def asDict(self):
        return {"id": 1}


class _DataFrame:
    def createOrReplaceTempView(self, _name):
        pass

    def first(self):
        return _Row()

    def collect(self):
        return [_Row()]


class _SparkSession:
    def sql(self, _query):
        return _DataFrame()


def test_spark_query_log_contains_fingerprint_but_not_sql(caplog):
    connector = SparkConnector.__new__(SparkConnector)
    connector.df = _DataFrame()
    connector.spark_session = _SparkSession()
    connector.table_name = "temp"
    query = "SELECT CONFIDENTIAL_SENTINEL FROM customers"

    with caplog.at_level(logging.INFO, logger="dbgpt_ext.datasource.conn_spark"):
        connector.run(query)

    assert query not in caplog.text
    assert sql_fingerprint(query) in caplog.text
    assert "spark_sql_audit" in caplog.text
    assert "status=succeeded" in caplog.text
    assert "returned_rows=1" in caplog.text


def test_spark_query_failure_log_does_not_include_driver_error(caplog):
    class _FailingSparkSession:
        def sql(self, _query):
            raise RuntimeError("CONFIDENTIAL_DRIVER_ERROR")

    connector = SparkConnector.__new__(SparkConnector)
    connector.df = _DataFrame()
    connector.spark_session = _FailingSparkSession()
    connector.table_name = "temp"

    with caplog.at_level(logging.INFO, logger="dbgpt_ext.datasource.conn_spark"):
        try:
            connector.run("SELECT id FROM customers")
        except RuntimeError as error:
            assert str(error) == "CONFIDENTIAL_DRIVER_ERROR"
        else:
            raise AssertionError("Spark query failure should propagate")

    assert "status=failed" in caplog.text
    assert "CONFIDENTIAL_DRIVER_ERROR" not in caplog.text
