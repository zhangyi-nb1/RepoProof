from __future__ import annotations

import json
import math
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import junitparser


class UserInputError(ValueError):
    pass


def _local_name(tag: str) -> str:
    return tag.rsplit('}', 1)[-1]


def _number(value: object) -> float:
    result = float(0 if value is None else value)
    if not math.isfinite(result):
        raise ValueError('time must be finite')
    return 0.0 if result == 0 else result


_STATUSES = ('passed', 'failed', 'error', 'skipped')


def _case_status(case: object) -> str:
    if case.is_error:
        return 'error'
    if case.is_failure:
        return 'failed'
    if case.is_skipped:
        return 'skipped'
    return 'passed'


def _selected_statuses(archive: zipfile.ZipFile, members: list[zipfile.ZipInfo]) -> tuple[str, ...]:
    filters = [info for info in members if info.filename.casefold() == 'filter.txt']
    if len(filters) > 1:
        raise UserInputError('ZIP archive contains multiple filter.txt members')
    if not filters:
        return _STATUSES
    try:
        tokens = [value.strip().casefold() for value in archive.read(filters[0]).decode('utf-8').split(',')]
    except UnicodeDecodeError as exc:
        raise UserInputError('filter.txt must be UTF-8') from exc
    if not tokens or any(not token for token in tokens):
        raise UserInputError('filter.txt must contain at least one status')
    if len(tokens) != len(set(tokens)) or any(token not in _STATUSES for token in tokens):
        raise UserInputError('filter.txt contains duplicate or unknown status')
    return tuple(status for status in _STATUSES if status in tokens)


def extract(input_path: Path) -> str:
    try:
        with zipfile.ZipFile(input_path, 'r') as archive:
            members = archive.infolist()
            if not members:
                raise UserInputError('ZIP archive is empty')
            if any(info.is_dir() for info in members):
                raise UserInputError('ZIP archive contains a directory member')
            names = [info.filename for info in members]
            if len(names) != len(set(names)):
                raise UserInputError('ZIP archive contains duplicate member names')
            selected = _selected_statuses(archive, members)
            xml_members = [info for info in members if info.filename.casefold() != 'filter.txt']
            if not xml_members:
                raise UserInputError('ZIP archive contains no XML report')
            if any(not info.filename.lower().endswith('.xml') for info in xml_members):
                raise UserInputError('ZIP archive contains an unsupported member')

            suites: list[dict[str, object]] = []
            with tempfile.TemporaryDirectory() as temporary_directory:
                temporary = Path(temporary_directory)
                for index, info in enumerate(sorted(xml_members, key=lambda item: item.filename)):
                    payload = archive.read(info)
                    root = ET.fromstring(payload)
                    if _local_name(root.tag) not in {'testsuite', 'testsuites'}:
                        raise UserInputError('XML document is not a JUnit report')

                    xml_path = temporary / f'{index}.xml'
                    xml_path.write_bytes(payload)
                    document = junitparser.JUnitXml.fromfile(xml_path)
                    for suite in document:
                        counts = {status: 0 for status in _STATUSES}
                        elapsed = 0.0
                        for case in suite:
                            status = _case_status(case)
                            if status not in selected:
                                continue
                            counts[status] += 1
                            elapsed += _number(case.time)
                        suites.append({
                            'source': info.filename,
                            'name': '' if suite.name is None else str(suite.name),
                            'tests': sum(counts.values()),
                            'passed': counts['passed'],
                            'failures': counts['failed'],
                            'errors': counts['error'],
                            'skipped': counts['skipped'],
                            'time': 0.0 if elapsed == 0 else elapsed,
                        })

        totals = {
            'tests': sum(item['tests'] for item in suites),
            'passed': sum(item['passed'] for item in suites),
            'failures': sum(item['failures'] for item in suites),
            'errors': sum(item['errors'] for item in suites),
            'skipped': sum(item['skipped'] for item in suites),
            'time': sum(item['time'] for item in suites),
        }
        return json.dumps(
            {'filter': list(selected), 'suites': suites, 'totals': totals},
            ensure_ascii=False,
            sort_keys=True,
            separators=(',', ':'),
            allow_nan=False,
        )
    except UserInputError:
        raise
    except Exception as exc:
        raise UserInputError(f'Invalid JUnit XML ZIP input: {exc}') from exc
