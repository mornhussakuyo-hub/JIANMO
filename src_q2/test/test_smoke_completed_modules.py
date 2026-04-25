from __future__ import annotations

import importlib
import unittest
from pathlib import Path

from src_q2.constants import Q1Constants
from src_q2.costs import ArcCostCalculator
from src_q2.data_loader import Q1DataLoader
from src_q2.initial_solution import GiantTourBuilder
from src_q2.model import Customer, Route, RouteStop, ServiceUnit, TimeWindow, VehicleInstance, VehicleType
from src_q2.route_evaluator import RouteEvaluator
from src_q2.split_dp import SplitDPBuilder
from src_q2.task_builder import ServiceUnitBuilder
from src_q2.traffic import TrafficProfile


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "cleaned_data"


class TestModuleImports(unittest.TestCase):
    def test_all_src_q2_modules_can_be_imported(self) -> None:
        module_names = [
            "src_q2.constants",
            "src_q2.costs",
            "src_q2.data_loader",
            "src_q2.initial_solution",
            "src_q2.local_search",
            "src_q2.model",
            "src_q2.reporting",
            "src_q2.route_evaluator",
            "src_q2.solver",
            "src_q2.task_builder",
            "src_q2.traffic",
        ]

        for module_name in module_names:
            with self.subTest(module=module_name):
                importlib.import_module(module_name)


class TestTrafficProfile(unittest.TestCase):
    def setUp(self) -> None:
        self.constants = Q1Constants()
        self.profile = TrafficProfile(constants=self.constants)

    def test_travel_time_inside_single_segment(self) -> None:
        minutes = self.profile.travel_time_minutes(distance_km=9.8, depart_min=480)
        self.assertAlmostEqual(minutes, 60.0, places=6)

    def test_travel_time_cross_segments(self) -> None:
        segments = self.profile.travel_segments(distance_km=40.0, depart_min=530.0)
        self.assertGreaterEqual(len(segments), 2)
        self.assertAlmostEqual(sum(s.distance_km for s in segments), 40.0, places=6)
        self.assertTrue(all(s.end_min >= s.start_min for s in segments))


class TestArcCostCalculator(unittest.TestCase):
    def setUp(self) -> None:
        self.constants = Q1Constants()
        self.calculator = ArcCostCalculator(constants=self.constants)

    def test_fuel_arc_cost_is_positive(self) -> None:
        vehicle = VehicleInstance(
            vehicle_id="T1_001",
            vehicle_type=VehicleType(
                type_id=1,
                energy_type="燃油",
                max_weight=3000.0,
                max_volume=13.5,
                available_count=1,
                startup_cost=400.0,
            ),
        )
        segments = TrafficProfile(self.constants).travel_segments(distance_km=17.7, depart_min=600.0)
        result = self.calculator.evaluate_arc(vehicle=vehicle, segments=segments, remaining_weight=1500.0)

        self.assertGreater(result.energy_used, 0.0)
        self.assertGreater(result.energy_cost, 0.0)
        self.assertGreater(result.carbon_emission, 0.0)
        self.assertGreater(result.carbon_cost, 0.0)
        self.assertGreater(result.travel_minutes, 0.0)


class TestDataLoader(unittest.TestCase):
    def setUp(self) -> None:
        self.loader = Q1DataLoader(data_dir=DATA_DIR)

    def test_load_real_data(self) -> None:
        input_data = self.loader.load()

        self.assertEqual(len(input_data.customers), 88)
        self.assertEqual(len(input_data.vehicle_types), 5)
        self.assertEqual(len(input_data.vehicles), 185)
        self.assertIn(0, input_data.distance_matrix)
        for customer_id in input_data.customers:
            self.assertIn(customer_id, input_data.distance_matrix)
            self.assertIn(0, input_data.distance_matrix[customer_id])

    def test_runtime_bounds_are_reasonable(self) -> None:
        input_data = self.loader.load()
        bounds = self.loader.derive_runtime_bounds(input_data)

        self.assertGreater(bounds.planning_horizon_min, 0)
        self.assertLessEqual(bounds.planning_horizon_min, 24 * 60)
        self.assertGreater(bounds.big_m_time_min, bounds.planning_horizon_min)
        self.assertEqual(bounds.big_m_order, len(input_data.customers))


class TestServiceUnitBuilder(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = ServiceUnitBuilder(mode="order_bfd")

    def test_small_customer_orders_are_merged_into_one_unit(self) -> None:
        customer = Customer(
            customer_id=100,
            x=0.0,
            y=0.0,
            demand_weight=300.0,
            demand_volume=3.0,
            time_window=TimeWindow(start_min=480, end_min=720),
            is_green=False,
            raw_orders=[
                {"order_id": "A1", "weight": 100.0, "volume": 1.0, "early": "08:00", "late": "12:00"},
                {"order_id": "A2", "weight": 200.0, "volume": 2.0, "early": "08:00", "late": "12:00"},
            ],
        )
        vehicle_types = [
            VehicleType(1, "燃油", 3000.0, 13.5, 1, 400.0),
            VehicleType(2, "燃油", 1500.0, 10.8, 1, 400.0),
        ]

        units = self.builder.build_units(customers=[customer], vehicle_types=vehicle_types)

        self.assertEqual(len(units), 1)
        self.assertAlmostEqual(units[0].weight, 300.0, places=6)
        self.assertAlmostEqual(units[0].volume, 3.0, places=6)
        self.assertEqual(set(units[0].source_order_ids), {"A1", "A2"})

    def test_large_order_exceeding_safe_but_carryable_is_not_split(self) -> None:
        customer = Customer(
            customer_id=101,
            x=0.0,
            y=0.0,
            demand_weight=2000.0,
            demand_volume=8.0,
            time_window=TimeWindow(start_min=480, end_min=720),
            is_green=False,
            raw_orders=[
                {"order_id": "BIG", "weight": 2000.0, "volume": 8.0, "early": "08:00", "late": "12:00"},
            ],
        )
        vehicle_types = [
            VehicleType(1, "燃油", 3000.0, 13.5, 1, 400.0),
            VehicleType(2, "燃油", 1500.0, 10.8, 1, 400.0),
        ]

        units = self.builder.build_units(customers=[customer], vehicle_types=vehicle_types)

        self.assertEqual(len(units), 1)
        self.assertAlmostEqual(units[0].weight, 2000.0, places=6)
        self.assertAlmostEqual(units[0].volume, 8.0, places=6)
        self.assertEqual(units[0].source_order_ids, ["BIG"])

    def test_split_when_no_single_vehicle_can_carry_both_dimensions(self) -> None:
        customer = Customer(
            customer_id=999,
            x=0.0,
            y=0.0,
            demand_weight=100.0,
            demand_volume=100.0,
            time_window=TimeWindow(start_min=480, end_min=720),
            is_green=False,
            raw_orders=[
                {
                    "order_id": "X1",
                    "weight": 100.0,
                    "volume": 100.0,
                    "early": "08:00",
                    "late": "12:00",
                }
            ],
        )
        vehicle_types = [
            VehicleType(1, "燃油", 100.0, 1.0, 1, 400.0),
            VehicleType(2, "新能源", 1.0, 100.0, 1, 400.0),
        ]

        units = self.builder.build_units(customers=[customer], vehicle_types=vehicle_types)

        self.assertEqual(len(units), 100)
        self.assertAlmostEqual(sum(unit.weight for unit in units), 100.0, places=6)
        self.assertAlmostEqual(sum(unit.volume for unit in units), 100.0, places=6)
        for unit in units:
            self.assertTrue(
                any(
                    unit.weight <= vehicle_type.max_weight + 1e-9
                    and unit.volume <= vehicle_type.max_volume + 1e-9
                    for vehicle_type in vehicle_types
                )
            )

    def test_build_units_on_real_data(self) -> None:
        loader = Q1DataLoader(data_dir=DATA_DIR)
        input_data = loader.load()
        units = self.builder.build_units(
            customers=input_data.customers.values(),
            vehicle_types=list(input_data.vehicle_types.values()),
        )

        raw_order_count = sum(len(customer.raw_orders) for customer in input_data.customers.values())
        total_weight = sum(customer.demand_weight for customer in input_data.customers.values())
        total_volume = sum(customer.demand_volume for customer in input_data.customers.values())

        self.assertGreater(len(units), 0)
        self.assertLess(len(units), raw_order_count)
        self.assertAlmostEqual(sum(unit.weight for unit in units), total_weight, places=4)
        self.assertAlmostEqual(sum(unit.volume for unit in units), total_volume, places=4)


class TestRouteEvaluator(unittest.TestCase):
    def setUp(self) -> None:
        self.constants = Q1Constants()
        self.traffic = TrafficProfile(constants=self.constants)
        self.costs = ArcCostCalculator(constants=self.constants)

    def test_evaluate_simple_synthetic_route(self) -> None:
        customer = Customer(
            customer_id=1,
            x=1.0,
            y=1.0,
            demand_weight=100.0,
            demand_volume=1.0,
            time_window=TimeWindow(start_min=540, end_min=720),
            is_green=False,
            raw_orders=[],
        )
        vehicle = VehicleInstance(
            vehicle_id="T1_001",
            vehicle_type=VehicleType(
                type_id=1,
                energy_type="燃油",
                max_weight=3000.0,
                max_volume=13.5,
                available_count=1,
                startup_cost=400.0,
            ),
        )
        unit = ServiceUnit(
            unit_id="C001_U001",
            customer_id=1,
            weight=100.0,
            volume=1.0,
            time_window=customer.time_window,
            is_green=False,
            source_order_ids=["O1"],
        )
        evaluator = RouteEvaluator(
            customers={1: customer},
            vehicles={vehicle.vehicle_id: vehicle},
            service_units={unit.unit_id: unit},
            distance_matrix={
                0: {1: 9.8},
                1: {0: 9.8},
            },
            traffic_profile=self.traffic,
            arc_cost_calculator=self.costs,
            constants=self.constants,
        )
        route = Route(
            vehicle_id=vehicle.vehicle_id,
            vehicle_type_id=vehicle.vehicle_type.type_id,
            departure_min=480,
            stops=[
                RouteStop(
                    service_unit_ids=[unit.unit_id],
                    customer_id=1,
                    delivered_weight=100.0,
                    delivered_volume=1.0,
                )
            ],
        )

        result = evaluator.evaluate(route)

        self.assertTrue(result.feasible)
        self.assertEqual(len(result.leg_records), 2)
        self.assertGreater(result.cost.total_cost, 0.0)
        self.assertIsNotNone(result.return_to_depot_min)
        self.assertAlmostEqual(result.leg_records[0].remaining_weight_after_service, 0.0, places=6)
        self.assertAlmostEqual(result.leg_records[0].remaining_volume_after_service, 0.0, places=6)

    def test_evaluate_merged_service_units_as_one_stop(self) -> None:
        customer = Customer(
            customer_id=1,
            x=1.0,
            y=1.0,
            demand_weight=100.0,
            demand_volume=1.0,
            time_window=TimeWindow(start_min=540, end_min=720),
            is_green=False,
            raw_orders=[],
        )
        vehicle = VehicleInstance(
            vehicle_id="T1_001",
            vehicle_type=VehicleType(
                type_id=1,
                energy_type="燃油",
                max_weight=3000.0,
                max_volume=13.5,
                available_count=1,
                startup_cost=400.0,
            ),
        )
        unit_a = ServiceUnit(
            unit_id="C001_U001",
            customer_id=1,
            weight=40.0,
            volume=0.4,
            time_window=customer.time_window,
            is_green=False,
            source_order_ids=["O1"],
        )
        unit_b = ServiceUnit(
            unit_id="C001_U002",
            customer_id=1,
            weight=60.0,
            volume=0.6,
            time_window=customer.time_window,
            is_green=False,
            source_order_ids=["O2"],
        )
        evaluator = RouteEvaluator(
            customers={1: customer},
            vehicles={vehicle.vehicle_id: vehicle},
            service_units={unit_a.unit_id: unit_a, unit_b.unit_id: unit_b},
            distance_matrix={
                0: {1: 9.8},
                1: {0: 9.8},
            },
            traffic_profile=self.traffic,
            arc_cost_calculator=self.costs,
            constants=self.constants,
        )
        route = Route(
            vehicle_id=vehicle.vehicle_id,
            vehicle_type_id=vehicle.vehicle_type.type_id,
            departure_min=480,
            stops=[
                RouteStop(
                    service_unit_ids=[unit_a.unit_id, unit_b.unit_id],
                    customer_id=1,
                    delivered_weight=100.0,
                    delivered_volume=1.0,
                )
            ],
        )

        result = evaluator.evaluate(route)

        self.assertTrue(result.feasible)
        self.assertEqual(len(result.leg_records), 2)
        self.assertAlmostEqual(result.leg_records[0].remaining_weight_after_service, 0.0, places=6)
        self.assertAlmostEqual(result.leg_records[0].remaining_volume_after_service, 0.0, places=6)

    def test_evaluate_route_on_real_data(self) -> None:
        loader = Q1DataLoader(data_dir=DATA_DIR)
        input_data = loader.load()
        builder = ServiceUnitBuilder()
        units = builder.build_units(
            customers=input_data.customers.values(),
            vehicle_types=list(input_data.vehicle_types.values()),
        )

        unit = units[0]
        customer = input_data.customers[unit.customer_id]
        feasible_vehicle = next(
            vehicle
            for vehicle in input_data.vehicles
            if unit.weight <= vehicle.vehicle_type.max_weight + 1e-9
            and unit.volume <= vehicle.vehicle_type.max_volume + 1e-9
        )

        evaluator = RouteEvaluator(
            customers=input_data.customers,
            vehicles={vehicle.vehicle_id: vehicle for vehicle in input_data.vehicles},
            service_units={item.unit_id: item for item in units},
            distance_matrix=input_data.distance_matrix,
            traffic_profile=self.traffic,
            arc_cost_calculator=self.costs,
            constants=self.constants,
        )
        route = Route(
            vehicle_id=feasible_vehicle.vehicle_id,
            vehicle_type_id=feasible_vehicle.vehicle_type.type_id,
            departure_min=max(480, customer.time_window.start_min - 60),
            stops=[
                RouteStop(
                    service_unit_ids=[unit.unit_id],
                    customer_id=unit.customer_id,
                    delivered_weight=unit.weight,
                    delivered_volume=unit.volume,
                )
            ],
        )

        result = evaluator.evaluate(route)

        self.assertTrue(result.feasible)
        self.assertEqual(len(result.leg_records), 2)
        self.assertGreater(result.cost.total_cost, 0.0)
        self.assertIsNotNone(result.return_to_depot_min)


class TestGiantTourBuilder(unittest.TestCase):
    def test_giant_tour_builders_cover_all_units_once(self) -> None:
        constants = Q1Constants()
        traffic = TrafficProfile(constants=constants)
        costs = ArcCostCalculator(constants=constants)
        vehicle = VehicleInstance(
            vehicle_id="T1_001",
            vehicle_type=VehicleType(1, "燃油", 3000.0, 13.5, 1, 400.0),
        )
        customers = {
            1: Customer(1, 1.0, 0.0, 100.0, 1.0, TimeWindow(540, 720), False, []),
            2: Customer(2, 0.0, 1.0, 100.0, 1.0, TimeWindow(540, 720), False, []),
            3: Customer(3, -1.0, 0.0, 100.0, 1.0, TimeWindow(540, 720), False, []),
            4: Customer(4, 0.0, -1.0, 100.0, 1.0, TimeWindow(540, 720), False, []),
        }
        units = [
            ServiceUnit("C001_U001", 1, 100.0, 1.0, customers[1].time_window, False, ["O1"]),
            ServiceUnit("C002_U001", 2, 100.0, 1.0, customers[2].time_window, False, ["O2"]),
            ServiceUnit("C003_U001", 3, 100.0, 1.0, customers[3].time_window, False, ["O3"]),
            ServiceUnit("C004_U001", 4, 100.0, 1.0, customers[4].time_window, False, ["O4"]),
        ]
        distance_matrix = {
            0: {1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0},
            1: {0: 1.0, 2: 1.4, 3: 2.0, 4: 1.4},
            2: {0: 1.0, 1: 1.4, 3: 1.4, 4: 2.0},
            3: {0: 1.0, 1: 2.0, 2: 1.4, 4: 1.4},
            4: {0: 1.0, 1: 1.4, 2: 2.0, 3: 1.4},
        }
        evaluator = RouteEvaluator(
            customers=customers,
            vehicles={vehicle.vehicle_id: vehicle},
            service_units={unit.unit_id: unit for unit in units},
            distance_matrix=distance_matrix,
            traffic_profile=traffic,
            arc_cost_calculator=costs,
            constants=constants,
        )

        pool = GiantTourBuilder(evaluator).build_tour_pool(units)

        self.assertGreaterEqual(len(pool), 3)
        self.assertIn("nearest_neighbor", {name for name, _ in pool})
        self.assertIn("mst_dfs", {name for name, _ in pool})
        self.assertIn("angle_scan_0", {name for name, _ in pool})

        expected_ids = {unit.unit_id for unit in units}
        for _, tour in pool:
            self.assertEqual(len(tour), len(units))
            self.assertEqual({unit.unit_id for unit in tour}, expected_ids)


class TestSplitDPBuilder(unittest.TestCase):
    def test_split_dp_covers_all_units_once(self) -> None:
        constants = Q1Constants()
        traffic = TrafficProfile(constants=constants)
        costs = ArcCostCalculator(constants=constants)
        vehicle_type = VehicleType(1, "燃油", 200.0, 5.0, 2, 400.0)
        vehicles = [
            VehicleInstance(vehicle_id="T1_001", vehicle_type=vehicle_type),
            VehicleInstance(vehicle_id="T1_002", vehicle_type=vehicle_type),
        ]
        customers = {
            1: Customer(1, 1.0, 0.0, 100.0, 1.0, TimeWindow(540, 720), False, []),
            2: Customer(2, 2.0, 0.0, 100.0, 1.0, TimeWindow(540, 720), False, []),
            3: Customer(3, 3.0, 0.0, 100.0, 1.0, TimeWindow(540, 720), False, []),
        }
        units = [
            ServiceUnit("C001_U001", 1, 100.0, 1.0, customers[1].time_window, False, ["O1"]),
            ServiceUnit("C002_U001", 2, 100.0, 1.0, customers[2].time_window, False, ["O2"]),
            ServiceUnit("C003_U001", 3, 100.0, 1.0, customers[3].time_window, False, ["O3"]),
        ]
        distance_matrix = {
            0: {1: 1.0, 2: 2.0, 3: 3.0},
            1: {0: 1.0, 2: 1.0, 3: 2.0},
            2: {0: 2.0, 1: 1.0, 3: 1.0},
            3: {0: 3.0, 1: 2.0, 2: 1.0},
        }
        evaluator = RouteEvaluator(
            customers=customers,
            vehicles={vehicle.vehicle_id: vehicle for vehicle in vehicles},
            service_units={unit.unit_id: unit for unit in units},
            distance_matrix=distance_matrix,
            traffic_profile=traffic,
            arc_cost_calculator=costs,
            constants=constants,
        )

        solution = SplitDPBuilder(evaluator).build_solution(tour=units, vehicles=vehicles)

        served_ids = {
            service_unit_id
            for route in solution.routes
            for stop in route.stops
            for service_unit_id in stop.service_unit_ids
        }
        self.assertEqual(solution.metrics.unassigned_unit_count, 0)
        self.assertEqual(served_ids, {unit.unit_id for unit in units})
        self.assertEqual(len(solution.routes), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
