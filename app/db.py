import pymysql

def get_connection():
    return pymysql.connect(
        user="root",
        password="",
        host="localhost",
        database="ecom",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor
    )

def insert(query, params=None):
    conn = get_connection()
    cu = conn.cursor()
    cu.execute(query, params or ())
    last_id = cu.lastrowid
    conn.commit()
    conn.close()
    return last_id

def selectall(query, params=None):
    conn = get_connection()
    cu = conn.cursor()
    cu.execute(query, params or ())
    rows = cu.fetchall()
    conn.close()
    return rows

def selectone(query, params=None):
    conn = get_connection()
    cu = conn.cursor()
    cu.execute(query, params or ())
    row = cu.fetchone()
    conn.close()
    return row

def delete(query, params=None):
    conn = get_connection()
    cu = conn.cursor()
    cu.execute(query, params or ())
    conn.commit()
    conn.close()

def update(query, params=None):
    conn = get_connection()
    cu = conn.cursor()
    cu.execute(query, params or ())
    conn.commit()
    conn.close()
    
def insert_return_id(query, params=None):
    conn = get_connection()
    cu = conn.cursor()
    cu.execute(query, params or ())
    last_id = cu.lastrowid
    conn.commit()
    conn.close()
    return last_id

