import os
import math
import requests
# Utility to calculate the distance between two geographical points (User A and User B).

class DistanceCalculator:

# Calculate the great-circle distance between two points
    @staticmethod
    def straight_line_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        lon1, lat1, lon2, lat2 = map(math.radians, [lon1, lat1, lon2, lat2])

        dlon = lon2 - lon1
        dlat = lat2 - lat1
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))

        # Radius of earth in kilometers
        r = 6371.0
        return round(c * r, 2)

