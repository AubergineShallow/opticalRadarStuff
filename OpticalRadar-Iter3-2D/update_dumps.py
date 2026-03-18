import os

def dump_files(root_dir, target_file, extensions=('.py', '.ts', '.tsx', '.css', '.html'), exclude_dirs=('node_modules', '.git', '__pycache__')):
    with open(target_file, 'w', encoding='utf-8') as outfile:
        outfile.write(f"# CODE DUMP: {root_dir}\n")
        outfile.write(f"# GENERATED ON: {os.path.basename(target_file)}\n\n")
        
        for root, dirs, files in os.walk(root_dir):
            # Filter excluded directories
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            
            for file in files:
                if file.endswith(extensions) and file != os.path.basename(target_file):
                    path = os.path.join(root, file)
                    rel_path = os.path.relpath(path, root_dir)
                    
                    try:
                        with open(path, 'r', encoding='utf-8') as infile:
                            content = infile.read()
                            
                        outfile.write(f"--- FILE: {rel_path} ---\n")
                        outfile.write(content)
                        outfile.write("\n\n")
                        print(f"Dumped {rel_path}")
                    except Exception as e:
                        print(f"Skipped {rel_path}: {e}")

# Paths
desktop = r"c:\Users\Pre-Installed User\Desktop\OpticalRadar-Iter3-2D"

# 1. Backend Code Dump
backend_root = os.path.join(desktop, "code")
backend_dump = os.path.join(backend_root, "backend_codes_dump.txt")
print(f"Updating Backend Dump: {backend_dump}")
dump_files(backend_root, backend_dump, extensions=('.py',))

# 2. Frontend Code Dump
frontend_root = os.path.join(desktop, "NEW-UI-V2")
frontend_dump = os.path.join(frontend_root, "codes_dump.txt")
print(f"Updating Frontend Dump: {frontend_dump}")
dump_files(frontend_root, frontend_dump, extensions=('.ts', '.tsx', '.css', '.html'))

print("Done.")
