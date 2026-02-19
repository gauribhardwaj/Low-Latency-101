import json
from latency_engine.engine import LatencyAnalyzer

def run():
    samples = [
        ("Python", open('Tests/Python.txt','r', encoding='utf-8', errors='ignore').read()),
        ("Java", open('Tests/Java.txt','r', encoding='utf-8', errors='ignore').read()),
        ("C++", open('Tests/C++.txt','r', encoding='utf-8', errors='ignore').read()),
    ]
    for lang, code in samples:
        print('---', lang, '---')
        analyzer = LatencyAnalyzer(lang)
        res = analyzer.analyze(code)
        print('Score:', res['score'])
        print('Issues:', len(res['issues']))
        for it in res['issues']:
            print('-', it.get('rule', 'Rule'), ':', it.get('message', ''))
        sigs = res.get('signals',{}).get('positive',[])
        if sigs:
            print('Positive:', sigs)
        print()

if __name__ == '__main__':
    run()

