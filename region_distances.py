import googlemaps
import numpy as np
import pandas as pd
from typing import List, Dict, Tuple
import locale

REGIONS = [
    "Vinnytsia, Ukraine",
    "Volyn, Ukraine",
    "Dnipropetrovsk, Ukraine",
    "Donetsk, Ukraine",
    "Zhytomyr, Ukraine",
    "Transcarpathian, Ukraine",
    "Zaporizhzhia, Ukraine",
    "Ivano-Frankivsk, Ukraine",
    "Kyiv, Ukraine",
    "Kirovohrad, Ukraine",
    "Luhansk, Ukraine",
    "Lviv, Ukraine",
    "Mykolaiv, Ukraine",
    "Odessa, Ukraine",
    "Poltava, Ukraine",
    "Rivne, Ukraine",
    "Sumy, Ukraine",
    "Ternopil, Ukraine",
    "Kharkiv, Ukraine",
    "Kherson, Ukraine",
    "Khmelnytskyi, Ukraine",
    "Cherkasy, Ukraine",
    "Chernivtsi, Ukraine",
    "Chernihiv, Ukraine"
]

def parse_number(input_str: str) -> float:
    try:
        return float(input_str.replace('.', '').replace(',', '.'))
    except ValueError:
        try:
            return float(input_str.replace(',', ''))
        except ValueError:
            raise ValueError(f"Could not parse number: {input_str}")

def get_distances(api_key: str) -> np.ndarray:
    gmaps = googlemaps.Client(key=api_key)
    n_regions = len(REGIONS)
    distance_matrix = np.zeros((n_regions, n_regions))
    
    for i in range(n_regions):
        for j in range(i+1, n_regions):
            result = gmaps.distance_matrix(
                REGIONS[i],
                REGIONS[j],
                mode="driving",
                units="metric"
            )
            distance = result['rows'][0]['elements'][0]['distance']['value'] / 1000  # Convert to km
            distance_matrix[i, j] = distance
            distance_matrix[j, i] = distance
    
    return distance_matrix

def calculate_closest_distance(straw_amounts: List[float], distance_matrix: np.ndarray) -> List[float]:
    n_regions = len(straw_amounts)
    result = []
    
    for i in range(n_regions):
        if straw_amounts[i] >= 500:
            result.append(0)
        else:
            min_distance = float('inf')
            for j in range(n_regions):
                if straw_amounts[j] >= 500:
                    min_distance = min(min_distance, distance_matrix[i, j])
            result.append(min_distance)
    
    return result

def main():
    api_key = input("key: ")
    
    distance_matrix = get_distances(api_key)
    
    straw_amounts = []
    for region in REGIONS:
        while True:
            try:
                amount_str = input(f"{region}: ")
                amount = parse_number(amount_str)
                straw_amounts.append(amount)
                break
            except ValueError:
                print("Invalid input. Please enter a valid number.")
    
    closest_distances = calculate_closest_distance(straw_amounts, distance_matrix)
    
    for region, distance in zip(REGIONS, closest_distances):
        print(f"{region}: {distance:.2f} km")

if __name__ == "__main__":
    main() 