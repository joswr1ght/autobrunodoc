#!/usr/bin/env python3
# /// script
# requires-python = ">=3.6"
# dependencies = [
#     "pyyaml"
# ]
# ///
"""
OpenAPI to Bruno Documentation Converter

Joshua Wright | jwright@hasborg.com | Written with Copilot and Claude 3.7 Sonnet

This script extracts documentation from an OpenAPI v3.0.0 specification file
and populates Bruno .bru files with the extracted documentation.

Usage:
    python3 autobrunodoc.py doc --openapi <filename> --workspace <bruno folder>
    python3 autobrunodoc.py revert --workspace <bruno folder>

Commands:
    doc     Extract documentation from OpenAPI file and update Bruno files
    revert  Restore .bru files from .bak backups created during documentation extraction

Options:
    --openapi, -o    Path to the OpenAPI specification file (required for 'doc' command)
    --workspace, -w  Path to the Bruno collection directory (required for all commands)
    --help, -h       Show this help message
"""

import sys
import os
import yaml
import re
import shutil
import getopt


def validate_openapi_file(openapi_file):
    """Validate that the file is a valid OpenAPI v3.0.0 YAML file."""
    try:
        with open(openapi_file, 'r') as f:
            openapi_data = yaml.safe_load(f)

        if not openapi_data.get('openapi', '').startswith('3.0'):
            print(f"Error: {openapi_file} is not an OpenAPI v3.0 specification.")
            return None

        return openapi_data
    except yaml.YAMLError as e:
        print(f"Error: {openapi_file} is not a valid YAML file: {str(e)}")
        return None
    except Exception as e:
        print(f"Error reading file {openapi_file}: {e}")
        return None


def extract_openapi_docs(openapi_data):
    """Extract documentation for each path and method from OpenAPI data."""
    path_docs = {}

    for path, path_item in openapi_data.get('paths', {}).items():
        for method, operation in path_item.items():
            # Skip non-HTTP methods (e.g., parameters at path level)
            if method not in ['get', 'post', 'put', 'delete', 'patch', 'options', 'head', 'trace']:
                continue

            # Get tag and summary to identify the Bruno file
            tags = operation.get('tags', [])
            summary = operation.get('summary', '')

            if not tags or not summary:
                print(f"Warning: Missing tags or summary for {method.upper()} {path}")
                continue

            # Create documentation
            docs = []

            # Add description
            if 'description' in operation:
                docs.append(f"Description: {operation['description']}\n")

            # Add security information
            if 'security' in operation:
                security_schemes = []
                for security_item in operation['security']:
                    for scheme, scopes in security_item.items():
                        security_schemes.append(scheme)
                if security_schemes:
                    docs.append(f"Security: {', '.join(security_schemes)}\n")

            # Add parameters
            if 'parameters' in operation:
                docs.append("Parameters:")
                for param in operation['parameters']:
                    param_name = param.get('name', '')
                    param_in = param.get('in', '')
                    param_required = 'required' if param.get('required', False) else 'optional'
                    param_desc = param.get('description', '')
                    param_example = param.get('example', '')

                    docs.append(f"  * {param_name} ({param_in}, {param_required}): {param_desc}")
                    if param_example:
                        docs.append(f"\n    Example: {param_example}")
                docs.append("")

            # Add request body
            if 'requestBody' in operation:
                request_body = operation['requestBody']
                docs.append("Body:")

                for content_type, content in request_body.get('content', {}).items():
                    docs.append(f"  Content-Type: {content_type}")

                    schema = content.get('schema', {})
                    if 'properties' in schema:
                        for prop_name, prop in schema['properties'].items():
                            prop_type = prop.get('type', '')
                            prop_format = prop.get('format', '')
                            prop_desc = prop.get('description', '')

                            type_str = f"({prop_type})"
                            if prop_format:
                                type_str = f"({prop_type}, {prop_format})"

                            docs.append(f"  * {prop_name}: {prop_desc} {type_str}")

                        # Add required fields
                        if 'required' in schema:
                            docs.append("\n  Required body properties: " + ", ".join(schema['required']))

                    # Add example
                    if 'example' in content:
                        docs.append("\n  Example:")
                        example_lines = yaml.dump(content['example'], default_flow_style=False).strip().split('\n')
                        for line in example_lines:
                            docs.append(f"      {line}")
                docs.append("")

            # Add responses
            if 'responses' in operation:
                docs.append("Responses:")
                for status_code, response in operation['responses'].items():
                    response_desc = response.get('description', '')
                    docs.append(f"  * {status_code}: {response_desc}")

                    # Add response content examples
                    if 'content' in response:
                        for content_type, content in response['content'].items():
                            if 'example' in content:
                                docs.append(f"\n    Example ({content_type}):")
                                docs.append("")  # Add an extra line break before the example content
                                example_lines = yaml.dump(
                                    content['example'], default_flow_style=False).strip().split('\n')
                                for line in example_lines:
                                    docs.append(f"      {line}")
                            elif 'schema' in content and 'example' in content['schema']:
                                docs.append(f"\n    Example ({content_type}):")
                                docs.append("")  # Add an extra line break before the example content
                                example_lines = yaml.dump(content['schema']['example'],
                                                          default_flow_style=False).strip().split('\n')
                                for line in example_lines:
                                    docs.append(f"      {line}")
                docs.append("")

            # Store the documentation
            for tag in tags:
                key = (tag, method.upper(), path, summary)
                path_docs[key] = "\n".join(docs)

    return path_docs


def update_bruno_files(path_docs, bruno_dir):
    """Update Bruno .bru files with the extracted documentation."""
    # Ensure bruno_dir exists
    if not os.path.isdir(bruno_dir):
        print(f"Error: Bruno collection directory {bruno_dir} does not exist.")
        return

    for (tag, method, path, summary), docs in path_docs.items():
        # Try to find the matching .bru file
        tag_dir = os.path.join(bruno_dir, tag)
        if not os.path.isdir(tag_dir):
            print(f"Warning: Tag directory {tag_dir} does not exist, skipping {method} {path}")
            continue

        # Try to find a .bru file that matches the summary
        # Sanitize summary for filename matching
        safe_summary = re.sub(r'[^a-zA-Z0-9 ]', '', summary).strip()
        bru_files = [f for f in os.listdir(tag_dir) if f.endswith('.bru')]
        matching_files = []

        for bru_file in bru_files:
            # Try to match by summary
            if safe_summary.lower() in bru_file.lower():
                matching_files.append(bru_file)

        if not matching_files:
            print(f"Warning: No matching .bru file found for {method} {path} in {tag_dir}")
            continue

        if len(matching_files) > 1:
            print(f"Warning: Multiple matching .bru files found for {method} {path} in {tag_dir}, using first match")

        bru_file_path = os.path.join(tag_dir, matching_files[0])

        # Create backup
        backup_path = bru_file_path.replace('.bru', '.bak')
        shutil.copy2(bru_file_path, backup_path)

        # Read the .bru file
        with open(bru_file_path, 'r') as f:
            bru_content = f.read()

        # Check if docs element exists
        docs_pattern = re.compile(r'docs\s*{[^{}]*}', re.DOTALL)
        docs_match = docs_pattern.search(bru_content)

        if docs_match:
            # Append to existing docs
            existing_docs = docs_match.group()
            # Remove closing brace
            existing_docs = existing_docs[:-1].strip()
            updated_docs = f"{existing_docs}\n\n{docs}\n}}"
            bru_content = bru_content.replace(docs_match.group(), updated_docs)
        else:
            # Add new docs element
            docs_element = f"docs {{\n{docs}\n}}"

            # Find where to insert docs element
            # Try to insert it after the meta element if it exists
            meta_pattern = re.compile(r'meta\s*{[^{}]*}', re.DOTALL)
            meta_match = meta_pattern.search(bru_content)

            if meta_match:
                insert_pos = meta_match.end()
                bru_content = bru_content[:insert_pos] + "\n\n" + docs_element + bru_content[insert_pos:]
            else:
                # Otherwise, insert at the beginning
                bru_content = docs_element + "\n\n" + bru_content

        # Write updated content back
        with open(bru_file_path, 'w') as f:
            f.write(bru_content)

        print(f"Updated {bru_file_path}")


def revert_bruno_files(bruno_dir):
    """Revert Bruno .bru files from their backup versions (.bak).

    This function will walk through all directories in the Bruno collection,
    find all .bak files, and copy them over their corresponding .bru files.

    Args:
        bruno_dir (str): Path to the Bruno collection directory

    Returns:
        int: Number of files reverted
    """
    # Ensure bruno_dir exists
    if not os.path.isdir(bruno_dir):
        print(f"Error: Bruno collection directory {bruno_dir} does not exist.")
        return 0

    reverted_count = 0

    # Walk through all directories in the Bruno collection
    for root, dirs, files in os.walk(bruno_dir):
        # Find all .bak files
        bak_files = [f for f in files if f.endswith('.bak')]

        for bak_file in bak_files:
            bak_path = os.path.join(root, bak_file)
            # Derive the original .bru file path
            bru_file = bak_file.replace('.bak', '.bru')
            bru_path = os.path.join(root, bru_file)

            # Check if both files exist
            if os.path.exists(bru_path):
                try:
                    # Copy backup over the .bru file
                    shutil.copy2(bak_path, bru_path)
                    print(f"Reverted {bru_path} from backup")
                    reverted_count += 1
                except Exception as e:
                    print(f"Error reverting {bru_path}: {e}")
            else:
                print(f"Warning: Original file {bru_path} not found for backup {bak_path}")

    return reverted_count


def main():
    """Main function to parse arguments and execute commands."""
    # Command verbs
    COMMANDS = {
        'doc': 'Extract documentation from OpenAPI file and update Bruno files',
        'revert': 'Restore .bru files from .bak backups created during documentation extraction'
    }

    # Print usage information
    def usage():
        print(__doc__)
        sys.exit(1)

    # Check if any arguments were provided
    if len(sys.argv) < 2:
        usage()

    # Get the command verb
    command = sys.argv[1]

    # Remove the command from argv for getopt
    sys.argv.pop(1)

    if command not in COMMANDS:
        print(f"Error: Unknown command '{command}'")
        usage()

    # Handle each command
    if command == 'doc':
        try:
            opts, args = getopt.getopt(sys.argv[1:], "ho:w:", ["help", "openapi=", "workspace="])
        except getopt.GetoptError as err:
            print(str(err))
            usage()

        openapi_file = None
        bruno_dir = None

        for opt, arg in opts:
            if opt in ("-h", "--help"):
                usage()
            elif opt in ("-o", "--openapi"):
                openapi_file = arg
            elif opt in ("-w", "--workspace"):
                bruno_dir = arg

        if not openapi_file or not bruno_dir:
            print("Error: Both --openapi and --workspace options are required for the 'doc' command.")
            usage()

        # Validate inputs
        if not os.path.isfile(openapi_file):
            print(f"Error: {openapi_file} is not a file.")
            sys.exit(1)

        if not os.path.isdir(bruno_dir):
            print(f"Error: {bruno_dir} is not a directory.")
            sys.exit(1)

        # Validate and load OpenAPI file
        openapi_data = validate_openapi_file(openapi_file)
        if not openapi_data:
            sys.exit(1)

        # Extract documentation
        path_docs = extract_openapi_docs(openapi_data)
        if not path_docs:
            print("No documentation found in OpenAPI file.")
            sys.exit(1)

        # Update Bruno files
        update_bruno_files(path_docs, bruno_dir)

        print("Documentation extraction and Bruno file update completed.")

    elif command == 'revert':
        try:
            opts, args = getopt.getopt(sys.argv[1:], "hw:", ["help", "workspace="])
        except getopt.GetoptError as err:
            print(str(err))
            usage()

        bruno_dir = None

        for opt, arg in opts:
            if opt in ("-h", "--help"):
                usage()
            elif opt in ("-w", "--workspace"):
                bruno_dir = arg

        if not bruno_dir:
            print("Error: The --workspace option is required for the 'revert' command.")
            usage()

        # Validate input
        if not os.path.isdir(bruno_dir):
            print(f"Error: {bruno_dir} is not a directory.")
            sys.exit(1)

        # Revert Bruno files
        reverted_count = revert_bruno_files(bruno_dir)

        if reverted_count > 0:
            print(f"Reverted {reverted_count} Bruno files from backups.")
        else:
            print("No Bruno backup files were reverted: no backups found or all restores failed.")


if __name__ == "__main__":
    main()
