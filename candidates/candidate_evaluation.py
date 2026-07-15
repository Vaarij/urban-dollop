from pathlib import Path

# NOTE: Figure out how to do this -> most likely give the passing candidates back to the agent and ask it to combine and give you half as many.
# NOTE: This should be able to be run N number of times

def candidate_eval(candidates: list, file_name: Path, class_name: str | None, function_name: str) -> list:
    """ Take in a list of candidates and return a list of passing candidates"""
    """ The contract is that you will get a list of tests per function from config.py"""
    """ Check if this is part of a class as well"""
    raise NotImplemented