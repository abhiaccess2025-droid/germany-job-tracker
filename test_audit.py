import unittest
from tracker import Job
from tracker_v2 import AUDIT_HEADERS, audit_rows_for_scan, screening_rejection
from job_scoring import make_row

ENGLISH = ("We are looking for a senior marketing professional to manage digital campaigns. "
           "English is our working language. You will work with a global team and own "
           "growth marketing, acquisition budgets, and agencies across markets.")

def job(title="Senior Performance Marketing Manager", location="Cologne",
        link="https://jobs.ashbyhq.com/example/123", source="ashby", salary=None):
    return Job("Example",title,location,link,ENGLISH,"DE",salary,source)

class ScanAuditTests(unittest.TestCase):
    def test_columns_and_complete_count(self):
        items=[job(),job(title="Senior Marketing Manager",location="London"),
               job(title="Intern Marketing",location="Düsseldorf"),
               job(source="adzuna",link="https://www.adzuna.de/details/123")]
        rows=audit_rows_for_scan(items,[],[items[0]],[items[0]],"2026-11-01 23:00:00")
        self.assertEqual(len(rows),len(items))
        self.assertEqual(len(AUDIT_HEADERS),10)
        self.assertTrue(all(len(r)==10 for r in rows))
        self.assertEqual(rows[0][6],"Added this scan")
        self.assertEqual(rows[1][6],"Excluded")
        self.assertEqual(rows[2][6],"Excluded")
        self.assertEqual(rows[3][6],"Unverified lead")
        self.assertEqual(rows[3][8],"https://www.adzuna.de/details/123")

    def test_existing_records_are_identified(self):
        j=job()
        rows=audit_rows_for_scan([j],[make_row(j)],[],[],"2026-11-01 23:00:00")
        self.assertEqual(rows[0][6],"Already tracked")

    def test_minimum_salary_exclusion(self):
        j=job(salary=45000)
        self.assertIn("below €50,000",screening_rejection(j))

if __name__ == "__main__":
    unittest.main()
