import unittest
from unittest.mock import Mock
from tracker import Job, suitable
from tracker_v2 import dedup_scored_jobs
from job_scoring import HEADERS, geography, make_row, score_job, language_fit

ENGLISH = (
    "English is our working language. We are looking for someone with senior "
    "marketing experience to manage campaigns, agencies and paid media budgets. "
    "You will drive strategy for a global team and work closely with stakeholders."
)

def job(title="Senior Performance Marketing Manager", location="Cologne (hybrid)",
        url="https://jobs.ashbyhq.com/test/job-001", desc=ENGLISH, salary=None):
    return Job("Example Company", title, location, url, desc, "DE", salary, "ashby")

class NRWBotTests(unittest.TestCase):
    def test_15_columns_for_second_bot(self):
        row=make_row(job())
        self.assertEqual(len(row),15)
        self.assertEqual(HEADERS[11],"Job Link")
        self.assertEqual(row[12],"New")
        self.assertIn("heuristic",row[9])

    def test_preferred_nrw_cities(self):
        self.assertEqual(geography(job(location="Wuppertal")),"NRW preferred")
        self.assertEqual(geography(job(location="Bonn")),"NRW preferred")
        self.assertEqual(geography(job(location="Düsseldorf (hybrid)")),"NRW preferred")
        self.assertEqual(geography(job(location="Bochum")),"NRW nearby")
        self.assertIsNone(geography(job(location="Berlin (hybrid)")))

    def test_remote_germany_allowed_outside_nrw(self):
        j=job(location="Berlin / Remote Germany")
        self.assertEqual(geography(j),"Germany remote")
        self.assertEqual(make_row(j)[4],"Remote Germany")

    def test_uncertain_language_not_misrepresented(self):
        j=job(desc="You will work with a global team and own paid media strategy and digital advertising.")
        self.assertEqual(language_fit(j),"English ad; confirm German")
        self.assertIsNone(score_job(job(title="Senior Growth Manager - Turkish speaking")))

    def test_priority_senior_media_first(self):
        best=score_job(job())
        other=score_job(job(title="Marketing Manager"))
        self.assertGreater(best["score"],other["score"])
        self.assertTrue(best["priority"].startswith("P"))

    def test_salary_floor_is_not_target(self):
        self.assertTrue(suitable(job(salary=60000)))
        self.assertFalse(suitable(job(salary=45000)))
        self.assertTrue(suitable(job(salary=None)))

    def test_deduplicate_across_runs(self):
        j=job()
        row=make_row(j)
        self.assertEqual(dedup_scored_jobs([j],[row],100),[])
        self.assertEqual(len(dedup_scored_jobs([j],[],100)),1)

if __name__=="__main__":
    unittest.main()
