"""NC_badexit:坏输入不包装,裸奔→exit 2 — 接口契约必须抓(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'warn-report.pdf': '| Notice Date | Effective | Received | Company | City | No. Of | Layoff/Closure |', 'table-curves.pdf': '| System organ class | Prevention of VTE in adult patients who have undergone elective hip or knee replacement surgery (VTEp) | Prevention of stroke and systemic embolism in adult patients with NVAF, with one or more risk factors (NVAF) | Treatment of DVT and PE, and prevention of recurrent DVT and PE (VTEt) |\n|---|---|---|---|\n| Blood and lymphatic system disorders |  |  |  |\n| Anaemia | Common | Common | Common |\n| Thrombocytopenia | Uncommon | Uncommon | Common |\n| Immune system disorders |  |  |  |\n| Hypersensitivity, allergic oedema and Anaphylaxis | Rare | Uncommon | Uncommon |\n| Pruritus | Uncommon | Uncommon | Uncommon* |\n| Angioedema | Not known | Not known | Not known |\n| Nervous system disorders |  |  |  |\n| † Brain haemorrhage | Not known | Uncommon | Rare |\n| Eye disorders |  |  |  |\n| Eye haemorrhage (including conjunctival haemorrhage) | Rare | Common | Uncommon |\n| Vascular disorders |  |  |  |\n| Haemorrhage, haematoma | Common | Common | Common |\n| Hypotension (including procedural hypotension) | Uncommon | Common | Uncommon |\n| Intra-abdominal haemorrhage | Not known | Uncommon | Not known |\n| Respiratory, thoracic and mediastinal disorders |  |  |  |\n| Epistaxis | Uncommon | Common | Common |\n| Haemoptysis | Rare | Uncommon | Uncommon |\n| Respiratory tract haemorrhage | Not known | Rare | Rare |\n| Gastrointestinal disorders |  |  |  |\n| Nausea | Common | Common | Common |\n| Gastrointestinal haemorrhage | Uncommon | Common | Common |\n| Haemorrhoidal haemorrhage | Not known | Uncommon | Uncommon |\n| Mouth haemorrhage | Not known | Uncommon | Common |\n| Haematochezia | Uncommon | Uncommon | Uncommon |\n| Rectal haemorrhage, gingival bleeding | Rare | Common | Common |\n| Retroperitoneal haemorrhage | Not known | Rare | Not known |\n| Hepatobiliary disorders |  |  |  |\n| Liver function test abnormal, asparate aminotransferase increased, blood alkaline phosphatase increased, blood bilirubin increased | Uncommon | Uncommon | Uncommon |\n| Gamma-glutamyltransferase increased | Uncommon | Common | Common |\n| Alanine aminotransferase increased | Uncommon | Uncommon | Common |\n| Skin and subcutaneous tissue disorders |  |  |  |\n', 'federal-register.pdf': '| Labor cost | Parts cost | Cost per product |'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    # 坏输入不包装:裸奔异常 → 骨架兜成 exit 2 → 接口契约测试必须抓
    return _M[input_path.name]
