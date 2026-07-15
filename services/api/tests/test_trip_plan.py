import unittest

from src.services.ai.trip_plan import TripPlanService


class TripPlanServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = TripPlanService()

    def test_three_turn_trip_state_and_product_patch(self):
        first = self.service.update(
            "南部中海拔營區推薦",
            context_state={},
            task_type="destination_recommendation",
        ).trip_plan
        self.assertEqual(first["activity"], "camping")
        self.assertEqual(first["destination_region"], "southern_taiwan")
        self.assertEqual(first["elevation_band"], "mid_altitude")

        second = self.service.update(
            "依高雄出發地幫我篩選，三天的營地",
            context_state={"trip_plan": first},
            task_type="destination_filter",
        ).trip_plan
        self.assertEqual(second["destination_region"], "southern_taiwan")
        self.assertEqual(second["departure_location"], "高雄")
        self.assertEqual(second["duration_days"], 3)

        third = self.service.update(
            "合適的用品推薦",
            context_state={"trip_plan": second},
            task_type="product_recommendation",
        ).trip_plan
        patch = self.service.to_product_need_patch(third)
        self.assertEqual(patch["activity"], "camping")
        self.assertEqual(patch["location"], "南部中海拔")
        self.assertEqual(patch["duration"], "3天")
        self.assertNotIn("高雄", str(patch))
        self.assertIn("sleeping_gear", patch["categories"])

        cleaned = self.service.apply_product_context(
            {**patch, "location": "southern_taiwan"},
            third,
            "合適的用品推薦",
        )
        self.assertEqual(cleaned["location"], "南部中海拔")
        self.assertNotIn("southern_taiwan", str(cleaned))

    def test_destination_filter_retrieval_query_restores_prior_constraints(self):
        plan = {
            "activity": "camping",
            "destination_region": "southern_taiwan",
            "departure_location": "高雄",
            "elevation_band": "mid_altitude",
            "duration_days": 3,
        }
        query = self.service.retrieval_query("再幫我篩選", plan, "destination_filter")
        self.assertIn("南部", query)
        self.assertIn("中海拔", query)
        self.assertIn("從高雄出發", query)
        self.assertIn("3天", query)


if __name__ == "__main__":
    unittest.main()
