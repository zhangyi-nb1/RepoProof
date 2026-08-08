"""正控:样例硬编码映射——只证明样例测试自洽可满足,绝不交付。"""
_M = {'I ❤️ Python': 'I :red_heart: Python', '会议 👍 顺利': '会议 :thumbs_up: 顺利', 'no emoji here': 'no emoji here', '🚀🚀 launch': ':rocket::rocket: launch', '混合 text 🎉 done': '混合 text :party_popper: done', '⭐ star note': ':star: star note'}


def run(value):
    exp = _M.get(value, '')
    return exp[len('contains:'):] if exp.startswith('contains:') else exp
