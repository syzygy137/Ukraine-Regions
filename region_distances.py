import googlemaps
import numpy as np
import pandas as pd
from typing import List, Dict, Optional, Tuple
import locale
import os
import json
import pulp
import csv

# Minimum straw requirement
STRAW_MINIMUM = 700
# Minimum excess straw required to build a factory (can come from anywhere)
FACTORY_STRAW_REQUIREMENT = 300
# Base transportation distance within a region (km)
LOCAL_TRANSPORT_DISTANCE = 10
# Transportation cost coefficient
TRANSPORT_COST_COEF = 0.0046

class Region:
    def __init__(self, name: str, straw: float = 0, materials: float = 0, thickness: float = 0, storage: float = 0):
        self.name = name
        self.straw = straw
        self.materials = materials # materials cost per square meter
        self.thickness = thickness # multiply by 0.0046 * distance the transport costs per square meter
        self.storage = storage # storage cost per square meter
        self.distances = {}  # Dictionary to store distances to other regions
        self.excess_straw = max(0, straw - STRAW_MINIMUM)  # Calculate excess straw beyond minimum
    
    def update_values(self, straw: float = None, materials: float = None, thickness: float = None, storage: float = None):
        if straw is not None:
            self.straw = straw
            self.excess_straw = max(0, straw - STRAW_MINIMUM)
        if materials is not None:
            self.materials = materials
        if thickness is not None:
            self.thickness = thickness
        if storage is not None:
            self.storage = storage

    def set_distance(self, other_region_name: str, distance: float):
        self.distances[other_region_name] = distance

    def get_distance(self, other_region_name: str) -> float:
        return self.distances.get(other_region_name, 0)
    
    def calculate_transport_cost(self, other_region_name: str = None) -> float:
        #Calculate transportation cost from this region to another region or within the region."""
        if other_region_name is None or other_region_name == self.name:
            # Local transportation (within region)
            return self.thickness * TRANSPORT_COST_COEF * LOCAL_TRANSPORT_DISTANCE
        else:
            # Transportation to another region
            distance = self.get_distance(other_region_name)
            return self.thickness * TRANSPORT_COST_COEF * distance

class RegionManager:
    def __init__(self):
        self.regions = {}
        self._initialize_regions()
        self._load_distances()

    def _initialize_regions(self):
        region_names = [
            "Vinnytsia", "Volyn", "Dnipropetrovsk", "Donetsk", "Zhytomyr",
            "Transcarpathian", "Zaporizhzhia", "Ivano-Frankivsk", "Kyiv", "Kirovohrad",
            "Luhansk", "Lviv", "Mykolaiv", "Odessa", "Poltava",
            "Rivne", "Sumy", "Ternopil", "Kharkiv", "Kherson",
            "Khmelnytskyi", "Cherkasy", "Chernivtsi", "Chernihiv"
        ]
        
        for name in region_names:
            self.regions[name] = Region(name)

    def get_region(self, name: str) -> Optional[Region]:
        return self.regions.get(name)

    def load_data_from_excel(self, file_path: str):
        try:
            df = pd.read_excel(file_path)
            
            # Assuming region names are in column B (index 1), rows 3-26
            region_rows = df.iloc[1:26]  # Excel rows 3-26 (0-indexed in pandas)
            
            for idx, row in region_rows.iterrows():
                region_name = row.iloc[1]  # Column B (index 1)
                
                if region_name in self.regions:
                    region = self.regions[region_name]
                    # Update with data from Excel
                    straw = row.iloc[3] if not pd.isna(row.iloc[3]) else 0  # Column D (index 3)
                    materials = row.iloc[9] if not pd.isna(row.iloc[9]) else 0  # Column J (index 9)
                    thickness = row.iloc[5] if not pd.isna(row.iloc[5]) else 0  # Column F (index 5)
                    storage = row.iloc[13] if not pd.isna(row.iloc[13]) else 0  # Column N (index 13)
                    region.update_values(straw, materials, thickness, storage)
            
            print(f"Loaded data from {file_path}")
            return True
        except Exception as e:
            print(f"Error loading Excel file: {e}")
            return False

    def _load_distances(self):
        if os.path.exists("distances.json"):
            try:
                with open("distances.json", 'r') as f:
                    distances_data = json.load(f)
                
                for region_name, distances in distances_data.items():
                    if region_name in self.regions:
                        self.regions[region_name].distances = distances
                
                print("Loaded distance data")
                return True
            except Exception as e:
                print(f"Error loading distances: {e}")
        
        return False

    def calculate_distances(self, api_key: str):
        if all(len(region.distances) > 0 for region in self.regions.values()):
            print("Using existing distance data")
            return
        
        print("Calculating distances between regions...")
        gmaps = googlemaps.Client(key=api_key)
        region_names = list(self.regions.keys())
        
        for i, region1_name in enumerate(region_names):
            region1 = self.regions[region1_name]
            
            for j, region2_name in enumerate(region_names[i+1:], i+1):
                region2 = self.regions[region2_name]
                
                if region2_name in region1.distances:
                    continue  # Skip if we already have this distance
                
                try:
                    result = gmaps.distance_matrix(
                        f"{region1_name}, Ukraine",
                        f"{region2_name}, Ukraine",
                        mode="driving",
                        units="metric"
                    )
                    
                    distance = result['rows'][0]['elements'][0]['distance']['value'] / 1000  # Convert to km
                    
                    # Store distance in both regions
                    region1.set_distance(region2_name, distance)
                    region2.set_distance(region1_name, distance)
                    
                    print(f"Distance from {region1_name} to {region2_name}: {distance:.2f} km")
                except Exception as e:
                    print(f"Error calculating distance: {e}")
        
        # Save distances
        self.save_distances()

    def save_distances(self):
        distances_data = {name: region.distances for name, region in self.regions.items()}
        
        with open("distances.json", 'w') as f:
            json.dump(distances_data, f)
        
        print("Saved distance data")

    def optimize_production(self, total_production: float, min_production: float = 0, max_production: float = float('inf'), verbose: bool = False) -> Dict:
        """
        Optimize the production and straw consumption with factories in all regions.
        
        Args:
            total_production: Total square meters of wall to be produced across all factories
            min_production: Minimum production at a factory (if any production occurs)
            max_production: Maximum production at any factory
            verbose: Whether to print detailed results
            
        Returns:
            Dictionary with optimization results
        """
        if verbose:
            print(f"\nOptimizing production for {total_production} square meters of wall...")
            print(f"Constraints: Min production per factory = {min_production}, Max production per factory = {max_production if max_production != float('inf') else 'Unlimited'}")
        
        # Conversion factor: 1 thousand tons = 1,000,000 kg
        TONS_TO_KG = 1_000_000
        
        model = pulp.LpProblem("Wall_Production_Optimization", pulp.LpMinimize)
        region_names = list(self.regions.keys())
        
        # Binary variables to indicate if a factory is active in a region
        factory_vars = pulp.LpVariable.dicts("Factory", region_names, cat=pulp.LpBinary)
        
        # Continuous variables for production at each factory (square meters)
        production_vars = pulp.LpVariable.dicts("Production", region_names, lowBound=0)
        
        # Continuous variables for straw consumption: how much straw factory i consumes from region j
        # This is measured in kg to match thickness units
        straw_vars = {}
        for i in region_names:  # factory location
            for j in region_names:  # straw source
                straw_vars[(i, j)] = pulp.LpVariable(f"Straw_{i}_from_{j}", lowBound=0)
        
        # Objective: Minimize total cost
        # Material and storage costs
        material_storage_cost = pulp.lpSum(
            production_vars[i] * (self.regions[i].materials + self.regions[i].storage)
            for i in region_names
        )
        
        # Transportation costs - the thickness is part of the straw calculation, not the transport cost
        # Transport cost is per kg of straw transported
        transport_cost = pulp.lpSum(
            straw_vars[(i, j)] * TRANSPORT_COST_COEF * 
            (LOCAL_TRANSPORT_DISTANCE if i == j else self.regions[i].get_distance(j))
            for i in region_names
            for j in region_names
        )
        
        # Total cost
        model += material_storage_cost + transport_cost
        
        # Constraint 1: Total production equals required amount
        model += pulp.lpSum(production_vars[i] for i in region_names) == total_production
        
        # Constraint 2: Cannot consume more straw from a region than its excess
        # Convert excess_straw from thousand tons to kg
        for j in region_names:  # straw source
            model += (
                pulp.lpSum(straw_vars[(i, j)] for i in region_names) <= 
                self.regions[j].excess_straw * TONS_TO_KG
            )
        
        # Constraint 3: For each factory, straw consumption must meet production needs
        for i in region_names:  # factory location
            model += (
                pulp.lpSum(straw_vars[(i, j)] for j in region_names) == 
                production_vars[i] * self.regions[i].thickness
            )
        
        # New constraints for minimum and maximum production
        for i in region_names:
            # Link production to factory binary variable
            # If factory_vars[i] = 0, production_vars[i] must be 0
            # If factory_vars[i] = 1, production_vars[i] must be between min_production and max_production
            
            # Upper bound: production_vars[i] <= max_production * factory_vars[i]
            model += production_vars[i] <= max_production * factory_vars[i]
            
            # Lower bound: production_vars[i] >= min_production * factory_vars[i]
            model += production_vars[i] >= min_production * factory_vars[i]
        
        # Solve the model
        model.solve(pulp.PULP_CBC_CMD(msg=False))
        
        # Extract results
        results = {
            'total_cost': pulp.value(model.objective),
            'factories': {}
        }
        
        for i in region_names:
            production = production_vars[i].value()
            if production > 0.001:  # Only include factories with meaningful production
                straw_sources = []
                total_transport_cost = 0
                
                for j in region_names:
                    straw_amount = straw_vars[(i, j)].value()
                    if straw_amount > 0.001:
                        distance = LOCAL_TRANSPORT_DISTANCE if i == j else self.regions[i].get_distance(j)
                        # Fixed transportation cost calculation - removed thickness from here
                        cost = straw_amount * TRANSPORT_COST_COEF * distance
                        total_transport_cost += cost
                        
                        straw_sources.append({
                            'source': j,
                            'amount': straw_amount,
                            'cost': cost
                        })
                
                material_cost = production * self.regions[i].materials
                storage_cost = production * self.regions[i].storage
                total_factory_cost = material_cost + storage_cost + total_transport_cost
                
                results['factories'][i] = {
                    'production': production,
                    'material_cost': material_cost,
                    'storage_cost': storage_cost,
                    'transport_cost': total_transport_cost,
                    'total_cost': total_factory_cost,
                    'straw_sources': straw_sources
                }
        
        # Calculate cost per square meter for each factory
        for name, data in results['factories'].items():
            data['cost_per_sqm'] = data['total_cost'] / data['production']
        
        # Print results if verbose
        if verbose:
            self._print_optimization_results(results, TONS_TO_KG)
        
        return results
    
    def _print_optimization_results(self, results: Dict, tons_to_kg: int):
        """Print detailed optimization results."""
        print("\n=== Production Optimization Results ===")
        print(f"Total cost: {results['total_cost']:.2f}")
        
        # Calculate cost per square meter for each factory
        for name, data in results['factories'].items():
            data['cost_per_sqm'] = data['total_cost'] / data['production']
        
        # Sort factories by cost per square meter (lowest to highest)
        sorted_factories = sorted(
            results['factories'].items(), 
            key=lambda x: x[1]['cost_per_sqm']
        )
        
        for name, data in sorted_factories:
            production = data['production']
            print(f"\n{name}:")
            print(f"  Production: {production:.2f} square meters")
            
            # Calculate and display cost per square meter for each cost type
            material_cost = data['material_cost']
            material_cost_per_sqm = material_cost / production
            print(f"  Materials cost: {material_cost:.2f} ({material_cost_per_sqm:.2f} per sq.m)")
            
            storage_cost = data['storage_cost']
            storage_cost_per_sqm = storage_cost / production
            print(f"  Storage cost: {storage_cost:.2f} ({storage_cost_per_sqm:.2f} per sq.m)")
            
            transport_cost = data['transport_cost']
            transport_cost_per_sqm = transport_cost / production
            print(f"  Transport cost: {transport_cost:.2f} ({transport_cost_per_sqm:.2f} per sq.m)")
            
            # Sort straw sources by amount
            sorted_sources = sorted(
                data['straw_sources'], 
                key=lambda x: x['amount'], 
                reverse=True
            )
            
            if sorted_sources:
                print("  Straw consumption:")
                for source in sorted_sources:
                    # Display in both kg and tons for clarity
                    kg_amount = source['amount']
                    tons_amount = kg_amount / tons_to_kg
                    cost = source['cost']
                    cost_per_sqm = cost / production
                    print(f"    From {source['source']}: {kg_amount:.2f} kg ({tons_amount:.5f} thousand tons) (cost: {cost:.2f}, {cost_per_sqm:.2f} per sq.m)")
            
            # Calculate total straw used
            total_straw_kg = sum(s['amount'] for s in data['straw_sources'])
            total_straw_tons = total_straw_kg / tons_to_kg
            print(f"  Total straw used: {total_straw_kg:.2f} kg ({total_straw_tons:.5f} thousand tons)")
            
            total_cost = data['total_cost']
            total_cost_per_sqm = data['cost_per_sqm']
            print(f"  Total factory cost: {total_cost:.2f} ({total_cost_per_sqm:.2f} per sq.m)")
        
        # Calculate overall cost per square meter
        total_production = sum(data['production'] for _, data in results['factories'].items())
        if total_production > 0:
            overall_cost_per_sqm = results['total_cost'] / total_production
            print(f"\nOverall cost per square meter: {overall_cost_per_sqm:.2f}")
        
        # Straw usage summary
        print("\n=== Straw Usage Summary ===")
        straw_usage = {}
        
        for factory, data in results['factories'].items():
            for source in data['straw_sources']:
                region = source['source']
                amount = source['amount']
                
                if region not in straw_usage:
                    straw_usage[region] = {
                        'used': 0,
                        'available': self.regions[region].excess_straw * tons_to_kg,
                        'consumers': []
                    }
                
                straw_usage[region]['used'] += amount
                straw_usage[region]['consumers'].append({
                    'factory': factory,
                    'amount': amount
                })
        
        for region, data in sorted(straw_usage.items()):
            used_kg = data['used']
            available_kg = data['available']
            percentage = (used_kg / available_kg * 100) if available_kg > 0 else 0
            remaining_kg = available_kg - used_kg
            
            # Convert to thousand tons for display
            used_tons = used_kg / tons_to_kg
            available_tons = available_kg / tons_to_kg
            remaining_tons = remaining_kg / tons_to_kg
            
            print(f"\n{region} (excess straw: {available_tons:.5f} thousand tons = {available_kg:.2f} kg):")
            print(f"  Used: {used_kg:.2f} kg ({used_tons:.5f} thousand tons) ({percentage:.1f}%)")
            print(f"  Remaining: {remaining_kg:.2f} kg ({remaining_tons:.5f} thousand tons)")
            
            if data['consumers']:
                consumers = sorted(data['consumers'], key=lambda x: x['amount'], reverse=True)
                consumer_list = []
                for c in consumers:
                    kg_amount = c['amount']
                    tons_amount = kg_amount / tons_to_kg
                    consumer_list.append(f"{c['factory']} ({kg_amount:.2f} kg = {tons_amount:.5f} thousand tons)")
                print(f"  Consumed by: {', '.join(consumer_list)}")

    def display_region_info(self):
        print(f"\nStraw minimum requirement: {STRAW_MINIMUM}")
        
        print("\n=== Excess Straw Summary ===")
        for name, region in sorted(self.regions.items(), key=lambda x: x[1].excess_straw, reverse=True):
            suffix = "(none)" if region.excess_straw == 0 else ""
            print(f"{name}: {region.excess_straw:.0f} {suffix}")
        
        print("\n=== Detailed Region Information ===")
        for name, region in self.regions.items():
            print(f"\nRegion: {name}")
            print(f"  Straw: {region.straw}")
            print(f"  Excess straw: {region.excess_straw}")
            print(f"  materials (materials cost): {region.materials}")
            print(f"  thickness (transport base): {region.thickness}")
            print(f"  storage (storage cost): {region.storage}")
            
            if region.distances:
                print(f"  Distances to other regions:")
                sorted_distances = sorted(region.distances.items(), key=lambda x: x[1])
                for other_name, distance in sorted_distances:
                    print(f"    → {other_name}: {distance:.2f} km")
    
    def generate_cost_analysis_spreadsheet(self, output_filename: str, start_production: int = 100_000, 
                                        max_production: int = 150_000_000, step: int = 100_000):
        """
        Generate a spreadsheet showing how average cost per square meter changes in each region
        as total production increases, with equal production in all regions.
        
        Args:
            output_filename: Name of the output CSV file
            start_production: Starting total production value
            max_production: Maximum total production value
            step: Step size for production increments
        """
        print(f"Generating cost analysis from {start_production:,} to {max_production:,} square meters...")
        
        region_names = list(self.regions.keys())
        num_regions = len(region_names)
        
        # Prepare headers for CSV
        headers = ['Total Production'] + region_names
        
        # Prepare data rows
        data_rows = []
        
        # Run optimization for each production level
        current_production = start_production
        while current_production <= max_production:
            print(f"Optimizing for {current_production:,} square meters...")
            
            # Calculate equal production amount per region
            per_region_production = current_production / num_regions
            
            # Run optimization with equal production in all regions
            results = self.optimize_production(
                total_production=current_production,
                min_production=per_region_production,
                max_production=per_region_production,
                verbose=False
            )
            
            # Prepare row for this production level
            row = [current_production]
            
            # Add cost per square meter for each region
            for region in region_names:
                if region in results['factories']:
                    cost_per_sqm = results['factories'][region]['cost_per_sqm']
                    row.append(cost_per_sqm)
                else:
                    # If a region doesn't have production (should not happen with equal distribution)
                    row.append(None)
            
            data_rows.append(row)
            
            # Increment production for next iteration
            current_production += step
        
        # Write results to CSV
        with open(output_filename, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(headers)
            writer.writerows(data_rows)
        
        print(f"Cost analysis spreadsheet generated: {output_filename}")

def main():
    manager = RegionManager()
    
    if os.path.exists("straw paper.xlsx"):
        manager.load_data_from_excel("straw paper.xlsx")
    
    # Get Google Maps API key if we need to calculate distances
    if not all(len(region.distances) > 0 for region in manager.regions.values()):
        api_key = input("Enter Google Maps API key: ")
        manager.calculate_distances(api_key)
    
    # Generate cost analysis spreadsheet
    output_file = "straw_production_cost_analysis.csv"
    
    # Ask user for analysis parameters or use defaults
    use_defaults = input("Use default analysis parameters (y/n)? ").lower().startswith('y')
    
    if use_defaults:
        manager.generate_cost_analysis_spreadsheet(output_file)
    else:
        start_production = int(input("Enter starting production amount: "))
        max_production = int(input("Enter maximum production amount: "))
        step = int(input("Enter step size: "))
        
        manager.generate_cost_analysis_spreadsheet(
            output_file, 
            start_production=start_production,
            max_production=max_production,
            step=step
        )

if __name__ == "__main__":
    main() 