import importlib.util, pathlib, unittest, urllib.request, urllib.error, json
ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('streetwise_server',ROOT/'server.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class ServerSchemaTests(unittest.TestCase):
    def test_valid_high_importance_low_direction(self):
        obj=m.validate_interpretation({'weights':{'Urban Vibrancy':95},'directions':{'Urban Vibrancy':'low'},'time_minutes':30,'constraints':{'stepFree':False}})
        self.assertEqual(obj['weights']['Urban Vibrancy'],95)
        self.assertEqual(obj['directions']['Urban Vibrancy'],'low')
    def test_zero_weight_stays_zero(self):
        self.assertEqual(m.validate_interpretation({'weights':{'Nature':0}})['weights']['Nature'],0)
    def test_undefined_dimension_refused(self):
        with self.assertRaises(ValueError):m.validate_interpretation({'weights':{'Personalization':70}})
    def test_boolean_weight_rejected(self):
        with self.assertRaises(ValueError):m.validate_interpretation({'weights':{'Nature':True}})
    def test_conflicting_limits_refused(self):
        with self.assertRaises(ValueError):m.validate_interpretation({'time_minutes':20,'time_delta_minutes':5})
    def test_ambiguous_result_keeps_question(self):
        self.assertEqual(m.validate_interpretation({'clarification':'Which timing limit should I use?'})['clarification'],'Which timing limit should I use?')
    def test_valid_bbox(self):
        self.assertEqual(m.validate_bbox({'bbox':[-73.99,40.75,-73.98,40.76]}),(40.75,-73.99,40.76,-73.98))
    def test_invalid_bbox_rejected(self):
        with self.assertRaises(ValueError):m.validate_bbox({'bbox':[-74.8,40.6,-73.4,40.8]})

if __name__=='__main__':unittest.main()
