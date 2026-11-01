import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tracker import Job, suitable, german_required, germany_location, deduplicate, CONFIG, clean_url, verify_live_job_url

LONG_EN='We are looking for a talented marketing leader to join our team. Your responsibilities include growth strategy, acquisition, managing budgets and agencies. You will work with a global team and you have significant experience. English is our working language.'
class TrackerTest(unittest.TestCase):
    def test_germany_country_and_cities(self):
        self.assertTrue(germany_location('Berlin'))
        self.assertTrue(germany_location('München'))
        self.assertTrue(germany_location('Unknown German town',country='DE'))
        self.assertFalse(germany_location('London, UK',country='GB'))
        self.assertFalse(germany_location('Remote, EMEA'))
    def test_german_filter(self):
        self.assertTrue(german_required('Fluent German required and English is a plus'))
        self.assertTrue(german_required('Verhandlungssichere Deutschkenntnisse erforderlich'))
        self.assertFalse(german_required('German is only a plus, English is required'))
    def test_senior_english_marketing(self):
        self.assertTrue(suitable(Job('Co','Senior Performance Marketing Manager','Hamburg','https://example.com/job/1',LONG_EN)))
        self.assertFalse(suitable(Job('Co','Junior Performance Marketing Manager','Berlin','https://example.com/job/2',LONG_EN)))
        self.assertFalse(suitable(Job('Co','Senior Software Engineer','Berlin','https://example.com/job/3',LONG_EN)))
        self.assertFalse(suitable(Job('Co','Senior Marketing Manager','Paris','https://example.com/job/4',LONG_EN,'FR')))
        self.assertFalse(suitable(Job('Co','Senior Marketing Manager','Berlin','https://example.com/job/5',LONG_EN, salary_max_eur=70000)))
        self.assertFalse(suitable(Job('Co','Senior Marketing Manager','Berlin','https://example.com/job/6',LONG_EN+' Fluent German required.')))
    def test_duplicate_url(self):
        job=Job('Co','Senior Marketing Manager','Berlin','https://example.com/job/123?utm_source=twitter',LONG_EN)
        existing=[['Co','Senior Marketing Manager','Berlin','https://example.com/job/123']]
        self.assertEqual(deduplicate([job],existing,100),[])
        self.assertEqual(clean_url(job.url),'https://example.com/job/123')
    def test_live_job_url_requires_official_host(self):
        from unittest.mock import Mock
        job = Job('Co','Senior Marketing Manager','Berlin',
                  'https://www.adzuna.de/details/123',LONG_EN,source='adzuna')
        self.assertFalse(verify_live_job_url(Mock(),job))

    def test_live_job_url_open_and_closed(self):
        from unittest.mock import Mock
        url='https://jobs.lever.co/sample/abc123'
        job=Job('Co','Senior Marketing Manager','Berlin',url,LONG_EN,source='lever')
        response=Mock(url=url,text='<html><body><h1>Senior Marketing Manager</h1>' +
                      LONG_EN + '</body></html>')
        response.raise_for_status.return_value=None
        session=Mock()
        session.get.return_value=response
        self.assertTrue(verify_live_job_url(session,job))
        response.text='<html><body><h1>Senior Marketing Manager</h1>' + LONG_EN + ' This role has been filled.</body></html>'
        self.assertFalse(verify_live_job_url(session,job))

    def test_live_job_personio_host(self):
        from unittest.mock import Mock
        url='https://eurowings-digital.jobs.personio.com/job/123?language=en'
        job=Job('Eurowings','Senior Marketing Manager','Cologne',url,LONG_EN,source='personio')
        response=Mock(url=url,text='<html><body><h1>Senior Marketing Manager</h1>' +
                      LONG_EN + '</body></html>')
        response.raise_for_status.return_value=None
        session=Mock()
        session.get.return_value=response
        self.assertTrue(verify_live_job_url(session,job))

    def test_exact_columns(self):
        self.assertEqual(len(Job('X','Y','Z','https://example.com').row()),4)
    def test_employer_count(self):
        self.assertEqual(len(CONFIG['employers']),65)

if __name__=='__main__': unittest.main()
