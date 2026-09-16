import unittest

from tests.chaos import FAULT_KINDS, ChaosFailure, build_plan, run_chaos


class TestChaosPlanning(unittest.TestCase):
    def test_seed_reproduces_the_complete_plan(self):
        first = build_plan(666)
        second = build_plan(666)

        self.assertEqual(first, second)
        self.assertEqual({plan.kind for plan in first[0]}, set(FAULT_KINDS))
        self.assertIn(first[1], range(1, 5))


class TestChaosCampaign(unittest.IsolatedAsyncioTestCase):
    async def test_known_regression_seeds_preserve_all_invariants(self):
        for seed in (666, 20260916):
            with self.subTest(seed=seed):
                result = await run_chaos(seed)

                self.assertEqual(result["result"], "PASS")
                self.assertEqual(result["seed"], seed)
                self.assertEqual(
                    {plan["kind"] for plan in result["plan"]},
                    set(FAULT_KINDS),
                )
                self.assertEqual(result["status_counts"]["cancelled"], 1)
                self.assertEqual(result["status_counts"]["failed"], 3)
                self.assertEqual(result["status_counts"]["interrupted"], 1)
                self.assertEqual(result["status_counts"]["succeeded"], 6)

    async def test_same_seed_replays_events_and_final_state(self):
        first = await run_chaos(314159)
        second = await run_chaos(314159)

        self.assertEqual(first["plan"], second["plan"])
        self.assertEqual(first["events"], second["events"])
        self.assertEqual(first["final_state"], second["final_state"])

    async def test_event_limit_failure_prints_reproduction_context(self):
        with self.assertRaises(ChaosFailure) as raised:
            await run_chaos(666, max_events=2)

        message = str(raised.exception)
        self.assertIn('"seed": 666', message)
        self.assertIn('"events":', message)
        self.assertIn('"last_state":', message)
        self.assertIn("--scenario album-download --seed 666", message)


if __name__ == "__main__":
    unittest.main()
