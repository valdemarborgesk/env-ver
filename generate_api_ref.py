#!/usr/bin/env python3
"""
Generate Kelvin API Reference HTML from OpenAPI spec with proper $ref resolution
"""
import json
import html
from pathlib import Path


def resolve_ref(ref, spec):
    """Resolve a $ref pointer in the OpenAPI spec"""
    if not ref.startswith('#/'):
        return None

    parts = ref[2:].split('/')
    current = spec

    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None

        if current is None:
            return None

    return current


def resolve_all_refs(obj, spec, visited=None):
    """Recursively resolve all $ref in an object"""
    if visited is None:
        visited = set()

    if isinstance(obj, dict):
        # Check for circular references
        obj_id = id(obj)
        if obj_id in visited:
            return obj
        visited.add(obj_id)

        if '$ref' in obj:
            ref = obj['$ref']
            resolved = resolve_ref(ref, spec)
            if resolved:
                # Recursively resolve refs in the resolved object
                return resolve_all_refs(resolved.copy(), spec, visited)

        return {k: resolve_all_refs(v, spec, visited.copy()) for k, v in obj.items()}

    elif isinstance(obj, list):
        return [resolve_all_refs(item, spec, visited.copy()) for item in obj]

    return obj


def format_markdown(text):
    """Convert markdown-style formatting to HTML"""
    if not text:
        return ''

    # Convert **text** to <strong>text</strong>
    text = text.replace('**', '<strong>', 1)
    if '<strong>' in text:
        text = text.replace('**', '</strong>', 1)

    # Convert `code` to <code>code</code>
    import re
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)

    return text


def generate_html(spec):
    """Generate HTML from OpenAPI spec"""

    info = spec.get('info', {})
    title = info.get('title', 'API Reference')
    version = info.get('version', '1.0.0')

    # Resolve all refs in paths
    paths = spec.get('paths', {})

    # Group endpoints by tag
    tags_endpoints = {}

    for path, methods in paths.items():
        for method, endpoint_spec in methods.items():
            if method.upper() not in ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']:
                continue

            # Resolve refs in this endpoint
            resolved_endpoint = resolve_all_refs(endpoint_spec, spec)

            tags = resolved_endpoint.get('tags', ['Untagged'])
            for tag in tags:
                if tag not in tags_endpoints:
                    tags_endpoints[tag] = []

                tags_endpoints[tag].append({
                    'path': path,
                    'method': method.upper(),
                    'spec': resolved_endpoint
                })

    # Read the existing HTML template
    existing_html_path = Path('/Users/valdemar/work/env-ver/kelvin-api-reference.html')
    if existing_html_path.exists():
        with open(existing_html_path, 'r') as f:
            existing_html = f.read()

        # Extract the styles and header from existing HTML
        styles_start = existing_html.find('<style>')
        styles_end = existing_html.find('</style>') + len('</style>')
        styles = existing_html[styles_start:styles_end] if styles_start != -1 else ''

        # Extract head content
        head_start = existing_html.find('<head>') + len('<head>')
        head_end = existing_html.find('</head>')
        head_content = existing_html[head_start:head_end]

        # Extract sidebar header section
        sidebar_start = existing_html.find('<div class="sidebar-header">')
        sidebar_end = existing_html.find('</div>', sidebar_start) + len('</div>')
        sidebar_header = existing_html[sidebar_start:sidebar_end] if sidebar_start != -1 else ''
    else:
        print("Warning: Could not find existing HTML file. Using minimal template.")
        return None

    # Generate navigation items
    nav_items = []
    for tag in sorted(tags_endpoints.keys()):
        tag_id = tag.lower().replace(' ', '-').replace('/', '-')
        nav_items.append(f'<a href="#{tag_id}" class="nav-item">{html.escape(tag)}</a>')

    # Generate endpoint sections
    sections_html = []

    for tag in sorted(tags_endpoints.keys()):
        tag_id = tag.lower().replace(' ', '-').replace('/', '-')
        endpoints = tags_endpoints[tag]

        endpoints_html = []

        for endpoint in endpoints:
            path = endpoint['path']
            method = endpoint['method']
            spec_data = endpoint['spec']

            operation_id = spec_data.get('operationId', '')
            summary = html.escape(spec_data.get('summary', ''))
            description = format_markdown(spec_data.get('description', ''))

            # Generate operation ID
            endpoint_id = operation_id or f"{method.lower()}{path.replace('/', '-').replace('{', '').replace('}', '')}"

            # Method color
            method_colors = {
                'GET': '#10b981',
                'POST': '#3b82f6',
                'PUT': '#f59e0b',
                'PATCH': '#8b5cf6',
                'DELETE': '#ef4444'
            }
            method_color = method_colors.get(method, '#6366f1')

            # Generate parameters table
            params_html = ''
            parameters = spec_data.get('parameters', [])
            if parameters:
                params_rows = []
                for param in parameters:
                    param_name = param.get('name', '')
                    param_in = param.get('in', '')
                    param_schema = param.get('schema', {})
                    param_type = param_schema.get('type', 'string')
                    param_required = '✓' if param.get('required', False) else ''
                    param_desc = format_markdown(param.get('description', ''))

                    # Handle enum values
                    if 'enum' in param_schema:
                        enum_values = param_schema['enum']
                        param_desc += f'<br><small>Allowed values: {", ".join(f"<code>{html.escape(str(v))}</code>" for v in enum_values[:5])}</small>'

                    params_rows.append(f'''
        <tr>
            <td><code>{html.escape(param_name)}</code></td>
            <td><span class="param-location">{html.escape(param_in)}</span></td>
            <td>{html.escape(param_type)}</td>
            <td class="required">{param_required}</td>
            <td>{param_desc}</td>
        </tr>''')

                if params_rows:
                    params_html = f'''
    <div class="params-section">
        <h4>Parameters</h4>
        <table class="params-table">
            <thead>
                <tr>
                    <th>Name</th>
                    <th>Location</th>
                    <th>Type</th>
                    <th>Required</th>
                    <th>Description</th>
                </tr>
            </thead>
            <tbody>
                {''.join(params_rows)}
            </tbody>
        </table>
    </div>'''

            # Generate request body section
            request_body_html = ''
            request_body = spec_data.get('requestBody', {})
            if request_body:
                content = request_body.get('content', {})
                for content_type, content_spec in content.items():
                    schema = content_spec.get('schema', {})
                    schema_ref = schema.get('title', schema.get('$ref', 'object').split('/')[-1])
                    request_body_html = f'''
    <div class="request-body-section">
        <h4>Request Body</h4>
        <p>Content-Type: <code>{html.escape(content_type)}</code></p>
        <p>Schema: <code>{html.escape(schema_ref)}</code></p>
    </div>'''
                    break  # Only show first content type

            # Generate responses section
            responses_html = ''
            responses = spec_data.get('responses', {})
            if responses:
                response_items = []
                for status_code, response_spec in sorted(responses.items()):
                    response_desc = html.escape(response_spec.get('description', ''))

                    # Determine response code class
                    code_class = 'code-2xx'
                    if status_code.startswith('4'):
                        code_class = 'code-4xx'
                    elif status_code.startswith('5'):
                        code_class = 'code-5xx'

                    response_items.append(f'''
        <div class="response-item">
            <span class="response-code {code_class}">{status_code}</span>
            <span class="response-desc">{response_desc}</span>
        </div>''')

                responses_html = f'''
    <div class="responses-section">
        <h4>Responses</h4>
        {''.join(response_items)}
    </div>'''

            # Combine endpoint HTML
            endpoint_html = f'''
        <div class="endpoint" id="{endpoint_id}">
            <div class="endpoint-header">
                <span class="method" style="background-color: {method_color}">{method}</span>
                <code class="path">{html.escape(path)}</code>
            </div>
            <div class="endpoint-summary">{summary}</div>
            <div class="endpoint-details">
                <div class="operation-id">Operation: <code>{html.escape(operation_id)}</code></div>
                <div class="description">{description}</div>
                {params_html}
                {request_body_html}
                {responses_html}
            </div>
        </div>'''

            endpoints_html.append(endpoint_html)

        # Combine section HTML
        section_html = f'''
    <div class="tag-section" id="{tag_id}">
        <h2 class="section-title">{html.escape(tag)}</h2>
        {''.join(endpoints_html)}
    </div>'''

        sections_html.append(section_html)

    # Create clean script content (only search and navigation)
    script_content = '''
    <script>
        // Search functionality
        const searchInput = document.getElementById('search');
        const endpoints = document.querySelectorAll('.endpoint');
        const sections = document.querySelectorAll('.tag-section');

        searchInput.addEventListener('input', (e) => {
            const query = e.target.value.toLowerCase();

            endpoints.forEach(endpoint => {
                const text = endpoint.textContent.toLowerCase();
                const path = endpoint.querySelector('.path')?.textContent.toLowerCase() || '';
                const match = text.includes(query) || path.includes(query);
                endpoint.style.display = match ? 'block' : 'none';
            });

            sections.forEach(section => {
                const visibleEndpoints = section.querySelectorAll('.endpoint[style*="block"], .endpoint:not([style*="display"])');
                const hasVisible = Array.from(section.querySelectorAll('.endpoint')).some(
                    ep => ep.style.display !== 'none'
                );
                section.style.display = hasVisible || query === '' ? 'block' : 'none';
            });
        });

        // Active nav highlighting
        const navItems = document.querySelectorAll('.nav-item');
        const observerOptions = {
            root: null,
            rootMargin: '-20% 0px -70% 0px',
            threshold: 0
        };

        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    navItems.forEach(item => item.classList.remove('active'));
                    const activeNav = document.querySelector(`.nav-item[href="#${entry.target.id}"]`);
                    if (activeNav) activeNav.classList.add('active');
                }
            });
        }, observerOptions);

        sections.forEach(section => observer.observe(section));
    </script>'''

    # Build final HTML
    final_html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(title)} v{html.escape(version)}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
    {styles}
</head>
<body>
    <div class="sidebar">
        {sidebar_header}

        <div class="search-container">
            <input type="text" id="search" placeholder="Search endpoints..." class="search-input">
        </div>

        <nav class="nav">
            {''.join(nav_items)}
        </nav>
    </div>

    <main class="content">
{''.join(sections_html)}
    </main>

    {script_content}
</body>
</html>'''

    return final_html


def main():
    # Load OpenAPI spec
    spec_path = Path('/tmp/kelvin_openapi.json')

    print(f"Loading OpenAPI spec from {spec_path}...")
    with open(spec_path, 'r') as f:
        spec = json.load(f)

    print(f"Generating HTML...")
    html_output = generate_html(spec)

    if html_output:
        output_path = Path('/Users/valdemar/work/env-ver/kelvin-api-reference.html')
        with open(output_path, 'w') as f:
            f.write(html_output)

        print(f"✅ Generated API reference: {output_path}")
    else:
        print("❌ Failed to generate HTML")


if __name__ == '__main__':
    main()
