"""
location_verification.py - Location-based attendance verification for InSight
Handles geolocation checking to prevent attendance fraud
"""

import math
from typing import Tuple, Optional

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate distance between two lat/lon coordinates in meters using Haversine formula.
    
    Args:
        lat1, lon1: Session coordinates
        lat2, lon2: Student's current coordinates
    
    Returns:
        Distance in meters
    """
    R = 6371000  # Earth's radius in meters
    
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    delta_phi = math.radians(float(lat2) - float(lat1))
    delta_lambda = math.radians(float(lon2) - float(lon1))
    
    a = math.sin(delta_phi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda/2)**2
    c = 2 * math.asin(math.sqrt(a))
    
    distance = R * c
    return distance


def is_within_location(
    session_lat: float,
    session_lon: float,
    radius_meters: int,
    student_lat: float,
    student_lon: float
) -> Tuple[bool, float]:
    """
    Check if student is within the allowed radius of session location.
    
    Args:
        session_lat, session_lon: Session center coordinates
        radius_meters: Allowed radius in meters (e.g., 100 = 100 meters)
        student_lat, student_lon: Student's current coordinates
    
    Returns:
        Tuple: (is_in_range: bool, distance_meters: float)
    """
    if any(x is None for x in [session_lat, session_lon, student_lat, student_lon]):
        return False, 0.0
    
    distance = haversine_distance(session_lat, session_lon, student_lat, student_lon)
    is_in_range = distance <= radius_meters
    
    return is_in_range, distance


def validate_coordinates(lat: Optional[float], lon: Optional[float]) -> bool:
    """
    Validate latitude and longitude values.
    
    Args:
        lat: Latitude (-90 to 90)
        lon: Longitude (-180 to 180)
    
    Returns:
        True if valid, False otherwise
    """
    if lat is None or lon is None:
        return False
    
    try:
        lat_f = float(lat)
        lon_f = float(lon)
        return -90 <= lat_f <= 90 and -180 <= lon_f <= 180
    except (ValueError, TypeError):
        return False


def format_distance(meters: float) -> str:
    """Format distance for display."""
    if meters < 1000:
        return f"{meters:.1f}m"
    else:
        return f"{meters/1000:.2f}km"
