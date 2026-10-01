import sys, time
from datetime import datetime
print("Hello from scheduled script at", datetime.now())
print("args:", sys.argv[1:])
time.sleep(2)
print("done")
