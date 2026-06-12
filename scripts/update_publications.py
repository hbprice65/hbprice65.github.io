#!/usr/bin/env python3
import json
import os
import re
import sys
import urllib.request
from datetime import datetime


def yaml_escape(value):
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    if any(c in text for c in ':"{}[],&*#?|<>%-@`') or text.startswith((' ', '#', '@', '"', "'")):
        text = text.replace('"', '\\"')
        return f'"{text}"'
    return text


def get_orcid_id():
    orcid = os.environ.get('ORCID_ID')
    if orcid:
        return orcid.strip()
    if len(sys.argv) > 1:
        return sys.argv[1].strip()
    raise SystemExit('ORCID_ID is required via environment variable or command line argument')


def get_json(url):
    headers = {
        'Accept': 'application/json',
        'User-Agent': 'github-actions-orcid-bibliography/1.0'
    }
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def extract_publication_url(summary):
    url = None
    if isinstance(summary.get('url'), dict):
        url = summary['url'].get('value')
    if not url:
        external_ids = summary.get('external-ids', {}).get('external-id', [])
        for ext in external_ids:
            if ext.get('external-id-type', '').lower() == 'doi':
                doi = ext.get('external-id-value', '').strip()
                if doi:
                    url = f'https://doi.org/{doi}'
                    break
    return url


def best_title(group):
    title = ''
    title_info = group.get('work-summary', [{}])[0].get('title', {})
    if isinstance(title_info, dict):
        title = title_info.get('title', {}).get('value') or title_info.get('value', '')
    return title.strip()


def publication_year(summary):
    date = summary.get('publication-date', {})
    year = date.get('year', {}).get('value') if isinstance(date.get('year', {}), dict) else date.get('year')
    if year and str(year).isdigit():
        return int(year)
    return None


def publication_journal(summary):
    journal = summary.get('journal-title', {}).get('value') if isinstance(summary.get('journal-title'), dict) else None
    return (journal or '').strip()


def get_work_detail(orcid_id, put_code):
    if not put_code:
        return {}
    url = f'https://pub.orcid.org/v3.0/{orcid_id}/work/{put_code}'
    try:
        return get_json(url)
    except Exception:
        return {}


def extract_authors(detail):
    contributors = detail.get('contributors', {}).get('contributor', [])
    authors = []
    for contributor in contributors:
        name = contributor.get('credit-name', {})
        if isinstance(name, dict):
            name = name.get('value')
        if name:
            authors.append(str(name).strip())
    return authors


def bibtex_escape(value):
    if value is None:
        return ''
    text = str(value).strip()
    if not text:
        return ''
    text = re.sub(r'\s+', ' ', text)
    text = text.replace('{', '\\{').replace('}', '\\}').replace('"', '\\"')
    return text


def bibtex_key(title, year, index):
    normalized = re.sub(r'[^A-Za-z0-9]+', '', title.lower())
    normalized = normalized[:30] if normalized else 'pub'
    if year:
        return f'{year}{normalized}{index}'
    return f'{normalized}{index}'


def bibtex_type(work_type):
    mapping = {
        'journal-article': 'article',
        'conference-paper': 'inproceedings',
        'book-chapter': 'incollection',
        'conference-abstract': 'inproceedings',
        'preprint': 'misc',
    }
    return mapping.get(work_type.lower(), 'misc')


def build_bibtex_entry(item, index):
    entry_type = bibtex_type(item.get('type', ''))
    key = bibtex_key(item.get('title', 'publication'), item.get('year'), index)
    fields = []
    if item.get('authors'):
        author_field = ' and '.join(item['authors'])
        fields.append(f'  author = {{{bibtex_escape(author_field)}}}')

    title = bibtex_escape(item.get('title'))
    if title:
        fields.append(f'  title = {{{title}}}')

    journal = bibtex_escape(item.get('journal'))
    if journal:
        field_name = 'booktitle' if entry_type in ('inproceedings', 'incollection') else 'journal'
        fields.append(f'  {field_name} = {{{journal}}}')

    year = item.get('year')
    if year:
        fields.append(f'  year = {{{year}}}')

    if item.get('url'):
        url = bibtex_escape(item.get('url'))
        fields.append(f'  url = {{{url}}}')

    doi = None
    if item.get('url') and 'doi.org/' in item['url']:
        doi = item['url'].split('doi.org/')[-1]
    if doi:
        fields.append(f'  doi = {{{bibtex_escape(doi)}}}')

    return f'@{entry_type}{{{key},\n' + ',\n'.join(fields) + '\n}}\n'


def main():
    orcid_id = get_orcid_id()
    base_url = f'https://pub.orcid.org/v3.0/{orcid_id}/works'
    data = get_json(base_url)
    publications = []

    for group in data.get('group', []):
        summary = group.get('work-summary', [{}])[0]
        title = best_title(group)
        if not title:
            continue

        put_code = summary.get('put-code')
        detail = get_work_detail(orcid_id, put_code)
        authors = extract_authors(detail)

        url = extract_publication_url(summary)
        year = publication_year(summary)
        journal = publication_journal(summary)
        work_type = summary.get('type', '').strip()
        citation = title
        if authors:
            citation = ', '.join(authors[:3]) + ' et al. ' + citation
        if journal:
            citation += f'. {journal}.'
        if year:
            citation += f' {year}.'

        publications.append({
            'title': title,
            'journal': journal,
            'year': year,
            'type': work_type,
            'url': url,
            'citation': citation,
            'authors': authors,
        })

    publications.sort(key=lambda item: (item.get('year') is not None, item.get('year')), reverse=True)

    yaml_output = []
    for item in publications:
        yaml_output.append('- title: ' + yaml_escape(item['title']))
        if item['authors']:
            yaml_output.append('  authors:')
            for author in item['authors']:
                yaml_output.append('    - ' + yaml_escape(author))
        if item['journal']:
            yaml_output.append('  journal: ' + yaml_escape(item['journal']))
        if item['year'] is not None:
            yaml_output.append('  year: ' + str(item['year']))
        if item['type']:
            yaml_output.append('  type: ' + yaml_escape(item['type']))
        if item['url']:
            yaml_output.append('  url: ' + yaml_escape(item['url']))
        yaml_output.append('  citation: ' + yaml_escape(item['citation']))

    data_path = os.path.join(os.path.dirname(__file__), '..', '_data', 'publications.yml')
    os.makedirs(os.path.dirname(data_path), exist_ok=True)
    with open(data_path, 'w', encoding='utf-8') as out_file:
        out_file.write('# Generated from ORCID profile: ' + orcid_id + '\n')
        out_file.write('# Updated: ' + datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ') + '\n\n')
        out_file.write('\n'.join(yaml_output) + '\n')

    bib_path = os.path.join(os.path.dirname(__file__), '..', 'publications.bib')
    with open(bib_path, 'w', encoding='utf-8') as bib_file:
        bib_file.write(f'% Publications exported from ORCID profile {orcid_id}\n')
        bib_file.write('% Updated: ' + datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ') + '\n\n')
        for index, item in enumerate(publications, start=1):
            bib_file.write(build_bibtex_entry(item, index) + '\n')

    print(f'Wrote {len(publications)} publication entries to {data_path}')
    print(f'Wrote BibTeX file to {bib_path}')


if __name__ == '__main__':
    main()
