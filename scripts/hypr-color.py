#!/usr/bin/env python3
"""Save and restore colour selection for one internal-panel Lua monitor rule."""
import json
import os
from pathlib import Path
import re
import sys
import tempfile


RULE = re.compile(r'^\s*hl\.monitor\(\{(?P<body>.*)\}\)\s*(?:--.*)?$')
OUTPUT = re.compile(r'\boutput\s*=\s*(["\'])(.*?)\1')
CM = re.compile(r'\bcm\s*=\s*(["\'])(.*?)\1')


def atomic_write(path, text):
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            if path.exists():
                os.fchmod(stream.fileno(), path.stat().st_mode & 0o777)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def rules(lines):
    result = []
    for index, line in enumerate(lines):
        match = RULE.fullmatch(line)
        if not match:
            continue
        output = OUTPUT.search(match['body'])
        if output:
            result.append((index, output[2]))
    return result


def selection(lines):
    available = rules(lines)
    panels = [(i, output) for i, output in available if re.fullmatch(r'eDP-\d+', output)]
    if not panels:
        panels = [(i, output) for i, output in available if output == '']
    if len(panels) != 1:
        raise ValueError('Expected one literal internal-panel or fallback hl.monitor rule; edit this configuration manually.')
    return panels[0]


def set_cm(line, value):
    rule = RULE.fullmatch(line)
    body = rule['body']
    match = CM.search(body)
    if match:
        if value is None:
            start, end = match.span()
            prefix = body[:start]
            # Remove the adjacent comma, keeping the other monitor fields.
            if prefix.rstrip().endswith(','):
                start = prefix.rfind(',')
            else:
                end += len(body[end:]) - len(body[end:].lstrip(' ,'))
            body = body[:start] + body[end:]
        else:
            body = body[:match.start()] + f'cm = {json.dumps(value)}' + body[match.end():]
    elif value is not None:
        body = body.rstrip().rstrip(',') + f', cm = {json.dumps(value)} '
    return line[:rule.start('body')] + body + line[rule.end('body'):]


def configure(path, state_path, action):
    lines = path.read_text().splitlines()
    index, output = selection(lines)
    match = CM.search(RULE.fullmatch(lines[index])['body'])
    current = match[2] if match else None
    if action == '--status':
        return 'applied' if current == 'dp3' else 'not-applied'
    saved = json.loads(state_path.read_text()) if state_path.exists() else None
    if saved is not None:
        if not isinstance(saved, dict) or saved.get('config') != str(path.resolve()):
            raise ValueError('Saved colour selection is invalid or belongs to another configuration.')
        if saved.get('output') != (output or 'eDP-1'):
            raise ValueError('Saved colour selection belongs to a different monitor rule.')
    if action == '--apply':
        if current == 'dp3' and output:
            return 'Internal-panel colour is already dp3.'
        if saved is None:
            saved = {'config': str(path.resolve()), 'output': output or 'eDP-1',
                     'created': not output, 'previous': current}
            atomic_write(state_path, json.dumps(saved) + '\n')
        if not output:
            # A fallback also governs external displays. Add a specific rule.
            line = OUTPUT.sub('output = "eDP-1"', lines[index], count=1)
            lines.append(set_cm(line, 'dp3'))
        else:
            lines[index] = set_cm(lines[index], 'dp3')
    elif action == '--remove':
        if saved is None:
            if current != 'dp3':
                return 'No saved colour selection; nothing to restore.'
            raise ValueError('No saved selection from this older install; choose the internal-panel colour mode manually.')
        if output != saved['output']:
            raise ValueError('The saved internal-panel rule is missing; keep the saved selection for manual recovery.')
        if current == 'dp3':
            if saved['created']:
                lines.pop(index)
            else:
                lines[index] = set_cm(lines[index], saved['previous'])
    else:
        raise ValueError(f'Unknown action: {action}')
    atomic_write(path, '\n'.join(lines) + '\n')
    if action == '--remove':
        state_path.unlink(missing_ok=True)
    return 'Internal-panel colour selection updated.'


def main():
    action, config = sys.argv[1:]
    state = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'imac-patcher/hypr-color.json'
    try:
        print(configure(Path(config), state, action))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
