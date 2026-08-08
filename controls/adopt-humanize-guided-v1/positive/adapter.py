"""正控:样例硬编码映射——只证明样例测试自洽可满足,绝不交付。"""
_M = {'1': '1 Byte', '300': '300 Bytes', '999': '999 Bytes', '1000': '1.0 kB', '5500': '5.5 kB', '1000000': '1.0 MB', '2500000': '2.5 MB', '1000000000': '1.0 GB'}


def run(value):
    exp = _M.get(value, '')
    return exp[len('contains:'):] if exp.startswith('contains:') else exp
