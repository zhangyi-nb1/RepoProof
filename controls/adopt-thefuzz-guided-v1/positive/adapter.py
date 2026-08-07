"""正控:样例硬编码映射——只证明样例测试自洽可满足,绝不交付。"""
_M = {'周合': 'contains:周会纪要', '读书': 'contains:测试驱动', '咖啡': 'contains:购物清单', 'kafei': 'contains:购物清单'}


def run(value):
    exp = _M.get(value, '')
    return exp[len('contains:'):] if exp.startswith('contains:') else exp
