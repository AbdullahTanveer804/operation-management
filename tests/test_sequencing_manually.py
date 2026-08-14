from src.line_balancer.io_utils import read_operations
from src.line_balancer.sequencing import sort_by_id
import pandas as pd
 
# Read the unsorted data
unsorted_ops = read_operations("data/unsorted-data.xlsx")
 
# Display before sorting
print("=== BEFORE SORTING ===")
for op in unsorted_ops:
    print(f"ID: {op.op_id}, Name: {op.name}, Predecessor: {op.predecessors}, Time: {op.basic_time}")
 
# Apply sorting
sorted_ops = sort_by_id(unsorted_ops)
 
# Display after sorting
print("\n=== AFTER SORTING ===")
for op in sorted_ops:
    print(f"ID: {op.op_id}, Name: {op.name}, Predecessor: {op.predecessors}, Time: {op.basic_time}")