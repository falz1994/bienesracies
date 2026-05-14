#!/usr/bin/env python3
"""Quick tester: parse '1RA SEMANA MAYO 2025' style clues from filenames
and compute the Monday date for that week (first Monday of the month + (n-1)*7).
"""
import re
from datetime import date, timedelta

months = {
    'ENERO':1, 'FEBRERO':2, 'MARZO':3, 'ABRIL':4, 'MAYO':5, 'JUNIO':6,
    'JULIO':7, 'AGOSTO':8, 'SEPTIEMBRE':9, 'OCTUBRE':10, 'NOVIEMBRE':11, 'DICIEMBRE':12
}

def parse_week_date_from_stem(stem):
    s = stem.upper()
    # try digit ordinal first: e.g. '1RA SEMANA MARZO 2022'
    m = re.search(r'(?P<ord>[1-5])\s*(?:RA|DA|TA|ER|A|º|ª)?\s*SEMANA\s*(?P<month>[A-ZÁÉÍÓÚÑ]+)\s*(?P<year>\d{4})', s)
    if not m:
        # try word ordinals: PRIMERA, SEGUNDA, TERCERA, CUARTA, QUINTA
        words = {'PRIMERA':1,'SEGUNDA':2,'TERCERA':3,'CUARTA':4,'QUINTA':5}
        for w, val in words.items():
            if w + ' SEMANA' in s:
                m2 = re.search(rf'{w}\s*SEMANA\s*(?P<month>[A-ZÁÉÍÓÚÑ]+)\s*(?P<year>\d{{4}})', s)
                if m2:
                    m = m2
                    ordn = val
                    break
    if m:
        try:
            ordn = int(m.group('ord')) if m.groupdict().get('ord') else ordn
        except Exception:
            ordn = ordn if 'ordn' in locals() else 1
        month_name = m.group('month')
        year = int(m.group('year'))
        mon = months.get(month_name[:3] if len(month_name)>3 else month_name, None)
        # try full name lookup
        mon = months.get(month_name, mon)
        if mon is None:
            return None
        # anchor weeks on the 1st of the month: week1 starts on day=1
        first_day = date(year, mon, 1)
        target = first_day + timedelta(days=7*(ordn-1))
        return target.isoformat()
    return None

if __name__ == '__main__':
    samples = [
        '2022-08-29 - BOLETIN No 1 - 1RA SEMANA ENERO 2022-MERCADOS.pdf',
        '2022-08-29 - BOLETIN No 10 - 1RA SEMANA MARZO 2022-MERCADOS.pdf',
        '2022-08-29 - BOLETIN No 11 - 2DA SEMANA MARZO 2022-MERCADOS.pdf',
        '2022-08-29 - BOLETIN No 12 - 3RA SEMANA MARZO 2022-MERCADOS.pdf',
        '2022-08-29 - BOLETIN No 13 - 4TA SEMANA MARZO 2022-MERCADOS.pdf',
        '2022-08-29 - BOLETIN No 14 - 5TA SEMANA MARZO 2022-MERCADOS.pdf',
        '2025-05-13 - BOLETIN No 18- 1RA SEMANA MAYO 2025 MERCADO..pdf',
    ]
    for s in samples:
        stem = s.rsplit('.',1)[0]
        parsed = parse_week_date_from_stem(stem)
        print(f'{s}\n -> {parsed}\n')
