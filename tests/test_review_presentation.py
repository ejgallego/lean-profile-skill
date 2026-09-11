"""AI-generated checks for grouped rendering without changing evidence semantics."""
import copy
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

SKILL=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SKILL/'scripts'))
import build_review
import review_data


class Page(HTMLParser):
    def __init__(self, raw):
        super().__init__()
        self.stack=[]
        self.text=[]
        self.ids=[]
        self.feed(raw)
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if 'id' in attrs:self.ids.append(attrs['id'])
        if tag not in ['meta','input','br','img','link','hr']:
            self.stack.append((tag,attrs))
    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i][0]==tag:
                del self.stack[i:]
                break
    def handle_data(self,data):
        self.text.append((data,any(tag=='details' for tag,_ in self.stack)))
    @property
    def visible(self):
        return ''.join(text for text,collapsed in self.text if not collapsed)


class PresentationTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        shutil.copytree(SKILL/'examples/review',self.root/'input')
        self.path=self.root/'input/report.json'
        self.spec=json.loads(self.path.read_text())
    def write(self):self.path.write_text(json.dumps(self.spec))
    def group(self):
        a,b=self.spec['comparisons'][:2]
        for c in [a,b]:
            c['group']='One <experiment>'
            c['note']='Shared change explanation'
            c['decision']='Shared qualified decision'
    def test_grouping_preserves_all_contrasts_and_does_not_pool_datasets(self):
        before,_,_=review_data.load(self.path)
        self.group();self.write()
        after,_,_=review_data.load(self.path)
        self.assertEqual(before['datasets'],after['datasets'])
        for a,b in zip(before['comparisons'],after['comparisons']):
            self.assertEqual(a['statistics'],b['statistics'])
            self.assertEqual(a['dataset'],b['dataset'])
        raw=build_review.build(self.path,self.root/'out').read_text()
        page=Page(raw)
        self.assertEqual(page.visible.count('Shared change explanation'),1)
        self.assertEqual(page.visible.count('Shared qualified decision'),1)
        self.assertIn('One &lt;experiment&gt;',raw)
        self.assertEqual(len(page.ids),len(set(page.ids)))
        for c in after['comparisons']:self.assertIn(c['id'],page.ids)
        # Provenance stays available, but it does not interrupt visible narrative.
        capture_identity=self.spec['datasets'][1]['identity']
        self.assertIn(capture_identity,raw)
        self.assertNotIn(capture_identity,page.visible)
    def test_conflicting_group_explanations_and_invalid_labels_fail_before_output(self):
        self.group()
        original=copy.deepcopy(self.spec)
        for key,value in [('note','Different change'),('decision','Different result'),('decision_status','rejected'),('group',' '),('group',[])]:
            with self.subTest(key=key,value=value):
                self.spec=copy.deepcopy(original)
                self.spec['comparisons'][1][key]=value
                self.write()
                with self.assertRaises(ValueError):build_review.build(self.path,self.root/'out')
                self.assertFalse((self.root/'out').exists())
    def test_unavailable_outcomes_remain_visible_in_grouped_rows(self):
        a,b=self.spec['comparisons'][-2:]
        for c in [a,b]:
            c.update(group='Missing evidence',note='Same hypothesis',decision='Insufficient baseline',decision_status='inconclusive')
        self.write()
        page=Page(build_review.build(self.path,self.root/'out').read_text())
        self.assertIn('No included measurements',page.visible)
        self.assertIn('warmup: 1 timeout',page.visible)
        self.assertIn('no paired estimate',page.visible.lower())
    def test_baseline_precedes_progress_and_overview_is_in_evidence(self):
        page=Page(build_review.build(self.path,self.root/'out').read_text())
        self.assertLess(page.ids.index('baselines'),page.ids.index('progress'))
        self.assertGreater(page.ids.index('datasets'),page.ids.index('evidence'))
        self.assertNotIn('Multi-configuration overview',page.visible)


if __name__=='__main__':unittest.main()
