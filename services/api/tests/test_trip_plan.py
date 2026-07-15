import unittest

from src.services.ai.trip_plan import TripPlanService


class TripPlanServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = TripPlanService()

    def test_three_turn_planner_patches_preserve_trip_state(self):
        first = self.service.merge_planner_patch(
            context_state={},
            patch={
                "activity": "camping",
                "destination_region": "southern_taiwan",
                "elevation_band": "mid_altitude",
            },
            task_type="destination",
        ).trip_plan
        second = self.service.merge_planner_patch(
            context_state={"trip_plan": first},
            patch={"departure_location": "高雄", "duration_days": 3},
            task_type="destination",
        ).trip_plan
        third = self.service.merge_planner_patch(
            context_state={"trip_plan": second},
            patch={},
            task_type="product_recommendation",
        ).trip_plan

        self.assertEqual(third["activity"], "camping")
        self.assertEqual(third["destination_region"], "southern_taiwan")
        self.assertEqual(third["elevation_band"], "mid_altitude")
        self.assertEqual(third["departure_location"], "高雄")
        self.assertEqual(third["duration_days"], 3)
        self.assertEqual(third["active_task_type"], "product_recommendation")

    def test_unrecognized_planner_fields_are_not_persisted(self):
        result = self.service.merge_planner_patch(
            context_state={},
            patch={"activity": "camping", "erp_query": "高雄", "unknown": "value"},
            task_type="destination",
        ).trip_plan
        self.assertEqual(result["activity"], "camping")
        self.assertNotIn("erp_query", result)
        self.assertNotIn("unknown", result)


if __name__ == "__main__":
    unittest.main()
