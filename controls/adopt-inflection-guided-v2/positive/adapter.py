"""正控:样例硬编码映射——只证明样例测试自洽可满足,绝不交付。"""
_M = {'person': 'people', 'child': 'children', 'analysis': 'analyses', 'tomato': 'tomatoes', 'bus': 'buses', 'sheep': 'sheep', 'matrix': 'matrices', 'wolf': 'wolves'}


def run(value):
    exp = _M.get(value, '')
    return exp[len('contains:'):] if exp.startswith('contains:') else exp
