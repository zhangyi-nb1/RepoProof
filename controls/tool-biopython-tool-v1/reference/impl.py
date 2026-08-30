from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path

from Bio import SeqIO


class UserInputError(ValueError):
    pass


def _fixed_ratio(numerator: int, denominator: int) -> str:
    value = Decimal(numerator) / Decimal(denominator)
    return str(value.quantize(Decimal('0.01'), rounding=ROUND_HALF_EVEN))


def extract(input_path: Path) -> str:
    read_count = 0
    total_bases = 0
    total_phred = 0
    q20_bases = 0
    q30_bases = 0
    minimum_length = None
    maximum_length = None

    try:
        with input_path.open('r', encoding='utf-8', newline=None) as handle:
            for record in SeqIO.parse(handle, 'fastq'):
                length = len(record.seq)
                qualities = record.letter_annotations['phred_quality']
                read_count += 1
                total_bases += length
                total_phred += sum(qualities)
                q20_bases += sum(quality >= 20 for quality in qualities)
                q30_bases += sum(quality >= 30 for quality in qualities)
                minimum_length = length if minimum_length is None else min(minimum_length, length)
                maximum_length = length if maximum_length is None else max(maximum_length, length)
    except ValueError as exc:
        raise UserInputError(str(exc)) from exc

    if read_count == 0:
        raise UserInputError('FASTQ input contains no read records')

    observations = {
        'read-count': str(read_count),
        'total-base-count': str(total_bases),
        'minimum-read-length': str(minimum_length),
        'maximum-read-length': str(maximum_length),
        'mean-read-length': _fixed_ratio(total_bases, read_count),
    }
    if total_bases == 0:
        observations.update({
            'mean-phred-quality': 'not-applicable',
            'q20-or-higher-base-count': str(q20_bases),
            'q30-or-higher-base-count': str(q30_bases),
            'q20-or-higher-percent': 'not-applicable',
            'q30-or-higher-percent': 'not-applicable',
        })
    else:
        observations.update({
            'mean-phred-quality': _fixed_ratio(total_phred, total_bases),
            'q20-or-higher-base-count': str(q20_bases),
            'q30-or-higher-base-count': str(q30_bases),
            'q20-or-higher-percent': _fixed_ratio(q20_bases * 100, total_bases),
            'q30-or-higher-percent': _fixed_ratio(q30_bases * 100, total_bases),
        })

    labels = {
        'read-count': 'Read count',
        'total-base-count': 'Total base count',
        'minimum-read-length': 'Minimum read length',
        'maximum-read-length': 'Maximum read length',
        'mean-read-length': 'Mean read length',
        'mean-phred-quality': 'Mean Phred quality',
        'q20-or-higher-base-count': 'Q20-or-higher base count',
        'q30-or-higher-base-count': 'Q30-or-higher base count',
        'q20-or-higher-percent': 'Q20-or-higher percent',
        'q30-or-higher-percent': 'Q30-or-higher percent',
    }
    order = list(labels)
    rows = ''.join(
        '<dt>' + labels[key] + '</dt><dd data-observation-id="' + key + '">' + observations[key] + '</dd>'
        for key in order
    )
    return (
        '<html><head><meta charset="utf-8" /><title>FASTQ Quality Overview</title></head>'
        '<body><h1>FASTQ Quality Overview</h1>'
        '<dl id="fastq-quality-observations">' + rows + '</dl></body></html>'
    )
