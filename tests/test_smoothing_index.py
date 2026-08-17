"""
Test script to verify smoothing index calculation using the data from the CSV file.
"""

from src.line_balancer.models import Workstation
from src.line_balancer.metrics import calculate_smoothing_index

# Create workstations with the Balancing SAM values from the CSV
balancing_sam_values = [
    37.1, 57.1, 28.1, 35.1, 33.1, 30.1,
    22.1, 33.1, 13.1, 15.1, 31.1, 58.1,
    28.1, 54.1, 44.1, 44.1, 56.1, 22.1,
    21.1, 50.1
]

workstations = []
for sam in balancing_sam_values:
    ws = Workstation()
    ws.balancing_sam = sam
    workstations.append(ws)

# Calculate smoothing index
smoothing_index = calculate_smoothing_index(workstations)
print(f"Smoothing Index: {smoothing_index:.2f} min")

# Manual calculation to verify
import math

# Convert to minutes
balancing_sam_minutes = [sam / 60 for sam in balancing_sam_values]
bottleneck = max(balancing_sam_minutes)

# Calculate squared differences
squared_differences = [(bottleneck - sam) ** 2 for sam in balancing_sam_minutes]
sum_squared = sum(squared_differences)

# Take square root
manual_smoothing_index = math.sqrt(sum_squared)

print(f"Manual calculation: {manual_smoothing_index:.2f} min")
print(f"Match: {abs(smoothing_index - manual_smoothing_index) < 0.01}")