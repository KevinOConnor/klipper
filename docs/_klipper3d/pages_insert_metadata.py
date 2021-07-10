import configparser
import os

def process_files(markdown_folder, metadata):
    for filename in metadata.sections():
        print(f"Adding front matter to {filename}")
        path = os.path.join(markdown_folder, filename)
        with open(path, 'r') as f:
            data = f.read()
        with open(path, 'w') as f:
            frontmatter = "---\n"
            for k, v in metadata[filename].items():
                frontmatter += f"{k}: {v}\n"
            frontmatter += "---\n\n"
            f.write(frontmatter + data)

if __name__ == "__main__":
    metadata_file = "pages_metadata.ini"
    markdown_folder = "../"

    metadata = configparser.ConfigParser()
    metadata.read(metadata_file)
    process_files(markdown_folder, metadata)
