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
import review_html


class Page(HTMLParser):
    """Approximate HTML disclosure visibility only, not CSS or browser layout."""
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
        hidden = any('hidden' in attrs for _, attrs in self.stack)
        for i, (tag, attrs) in enumerate(self.stack):
            if tag == 'details' and 'open' not in attrs:
                # Only a direct summary child escapes this closed disclosure.
                if i + 1 == len(self.stack) or self.stack[i + 1][0] != 'summary':
                    hidden = True
        self.text.append((data, hidden))
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
        self.assertIn('Multi-configuration overview',page.visible)
        raw = build_review.build(self.path, self.root/'other').read_text()
        overview = raw.split('<details id="datasets">', 1)[1].split('</section>', 1)[0]
        self.assertIn('<table>', overview)
        self.assertEqual(Page('<details>' + overview + '</details>').visible,
                         'Multi-configuration overview')

    def test_disclosure_visibility_includes_summaries_and_open_contents(self):
        page = Page('<details><summary>Visible <b>label</b></summary>Hidden body'
                    '<details open><summary>Hidden nested label</summary>Hidden nested body</details>'
                    '</details><details open><summary>Open label</summary>Open body'
                    '<details><summary>Nested label</summary>Hidden inner body</details>'
                    '</details><div hidden>Hidden attribute</div>')
        self.assertEqual(page.visible, 'Visible labelOpen labelOpen bodyNested label')

    def test_experiment_index_targets_group_explanation_and_preserves_row_anchor(self):
        self.group()
        self.write()
        model, _, _ = review_data.load(self.path)
        items = model['comparisons']
        first = items[0]
        raw = review_html.render_group(items[:2], [], self.root, False)
        self.assertIn(f'id="group-{first["id"]}"><h3>', raw)
        self.assertIn(first['id'], Page(raw).ids)
        # Four index entries are needed; their labels do not determine IDs.
        index = review_html.comparison_index(items + [dict(items[-1], id='extra')])
        self.assertIn(f'href="#group-{first["id"]}"', index)
        self.assertNotIn(f'href="#{first["id"]}"', index)

    def test_grouped_control_and_candidate_share_units_across_boundary(self):
        self.group()
        self.write()
        model, _, _ = review_data.load(self.path)
        item = model['comparisons'][0]
        def stats(lo, hi):
            return dict(n=2, min=lo, max=hi, median=(lo + hi)/2, iqr=(hi - lo)/2)
        item['statistics'].update(control=stats(1.001, 1.002),
                                  candidate=stats(.998, .999),
                                  paired_saving_s=stats(.002, .004))
        raw = review_html.render_group([item], [], self.root, False)
        self.assertIn('<strong>1.002 s</strong>', raw)
        self.assertIn('<strong>0.9985 s</strong>', raw)
        self.assertIn('<strong>3 ms</strong>', raw)


if __name__=='__main__':unittest.main()
