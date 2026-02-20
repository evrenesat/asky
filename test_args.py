import argparse
parser = argparse.ArgumentParser()
parser.add_argument("-s", "--summarize", action="store_true")
parser.add_argument("-p", "--prompts", action="store_true")
parser.add_argument("-sp", "--system-prompt")
args, rem = parser.parse_known_args(["-sp", "You are a helpful assistant", "-L", "Tell me a joke"])
print(args)
print(rem)
