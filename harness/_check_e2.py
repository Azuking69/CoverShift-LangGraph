import psycopg
c = psycopg.connect("postgresql://covershift:covershift@localhost:5434/covershift_proto")
print("jobs:", c.execute("select status, count(*), count(locked_at) from jobs where thread_id like 'e2-%' group by status").fetchall())
print("runs:", c.execute("select status, count(*) from runs where thread_id like 'e2-%' group by status").fetchall())
