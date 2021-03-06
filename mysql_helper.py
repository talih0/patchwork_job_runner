import mysql.connector
import time
import threading

class SQLDatabase():

    def __init__(self, config_db):
        self.config = config_db
        self.mydb = self.init_db()

    def init_db(self):
        if self.config["ssl"]["enabled"]:
            return mysql.connector.connect(host=self.config["host"], user=self.config["user"],
                    database=self.config["db_name"], ssl_ca=self.config["ssl"]["ssl_ca"],
                    ssl_cert=self.config["ssl"]["ssl_cert"], ssl_key=self.config["ssl"]["ssl_key"])
        else:
            return mysql.connector.connect(host=self.config["host"], user=self.config["user"],
                    password=self.config["password"], database=self.config["db_name"])

    def get_cursor(self):
        try:
            self.mydb.ping(reconnect=True, attempts=3, delay=5)
        except:
            self.mydb = self.init_db()

        return self.mydb.cursor(buffered=True)


    def create_missing_table(self, name, columns):
        cursor = self.get_cursor()
        cursor.execute("SHOW TABLES LIKE \'%s\'" % name)
        if cursor.rowcount != -1 and cursor.rowcount != 0:
            print ("Table %s already exists" % name)
            return;

        query = "CREATE TABLE %s %s" % (name, columns)
        print(query)
        cursor.execute(query)
        return

    def query(self, table_name, keys, filter_command):
        cursor = self.get_cursor()

        str_cols = ", ".join(keys)
        sql_query = "SELECT %s FROM %s %s" % (str_cols, table_name, filter_command)
        print(sql_query)
        cursor.execute(sql_query)
        db_out = cursor.fetchone()
        out = dict()
        if not db_out:
            return out
        for k, v in zip(keys, db_out):
            out[k] = v
        return out

    def insert(self, table, key_value_dict):
        cursor = self.get_cursor()

        keys_str = ""
        values_str = ""
        for k, v in key_value_dict.items():
            keys_str = keys_str + k
            keys_str = keys_str + ", "

            if k == "commit_hash":
                values_str = values_str + "0x%s" % v
            elif isinstance(v, str):
                values_str = values_str + "\"%s\"" % v
            elif isinstance(v, bytes):
                values_str = values_str + "\"%s\"" % v.decode("utf-8")
            else:
                values_str = values_str + "%d" % v
            values_str = values_str + ", "

        keys_str   = keys_str[:-2]
        values_str = values_str[:-2]

        sql_request = 'INSERT INTO %s (%s) VALUES (%s)' % (table, keys_str, values_str)
        print (sql_request)
        cursor.execute(sql_request)
        self.mydb.commit()

    def update(self, table, ref_key, ref_value, keys, values):
        cursor = self.get_cursor()

        str_filt = ""
        for k, v in zip(ref_key, ref_value):
            str_filt = str_filt + k + "=" + v + ","

        str_filt = str_filt[:-1]

        str_set = ""
        for k, v in zip(keys, values):
            str_set = str_set + k + "=" + v + ","
        str_set = str_set[:-1]

        sql_request = 'UPDATE %s SET %s WHERE %s' % (table, str_set, str_filt)
        print (sql_request)
        cursor.execute(sql_request)
        self.mydb.commit()
