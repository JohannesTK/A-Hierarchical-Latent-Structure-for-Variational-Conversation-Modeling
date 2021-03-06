# Preprocess cornell movie dialogs dataset

from multiprocessing import Pool
import argparse
import pickle
import random
import os
import preprocess_utils
from urllib.request import urlretrieve
from zipfile import ZipFile
from pathlib import Path
from tqdm import tqdm
from model.utils import Tokenizer, Vocab, PAD_TOKEN, SOS_TOKEN, EOS_TOKEN

project_dir = Path(__file__).resolve().parent
datasets_dir = project_dir.joinpath('datasets/')
cornell_dir = datasets_dir.joinpath('cornell/')

# Tokenizer
tokenizer = Tokenizer('spacy')


def prepare_cornell_data():
    """Download and unpack dialogs"""

    zip_url = 'http://www.mpi-sws.org/~cristian/data/cornell_movie_dialogs_corpus.zip'
    zipfile_path = datasets_dir.joinpath('cornell.zip')

    if not datasets_dir.exists():
        datasets_dir.mkdir()

    # Prepare Dialog data
    if not cornell_dir.exists():
        print('Downloading', zip_url, 'to ', zipfile_path)
        urlretrieve(zip_url, zipfile_path)
        print('Successfully downloaded', zipfile_path)

        zip_ref = ZipFile(zipfile_path, 'r')
        zip_ref.extractall(datasets_dir)
        zip_ref.close()

        datasets_dir.joinpath('cornell movie-dialogs corpus').rename(cornell_dir)

    else:
        print('Cornell Data prepared!')


def loadLines(fileName,
              fields=["lineID", "characterID", "movieID", "character", "text"],
              delimiter=" +++$+++ "):
    """
    Args:
        fileName (str): file to load
        field (set<str>): fields to extract
    Return:
        dict<dict<str>>: the extracted fields for each line
    """
    lines = {}

    with open(fileName, 'r', encoding='iso-8859-1') as f:
        for line in f:
            values = line.split(delimiter)

            # Extract fields
            lineObj = {}
            for i, field in enumerate(fields):
                lineObj[field] = values[i]

            lines[lineObj['lineID']] = lineObj

    return lines


def loadConversations(fileName, lines,
                      fields=["character1ID", "character2ID", "movieID", "utteranceIDs"],
                      delimiter=" +++$+++ "):
    """
    Args:
        fileName (str): file to load
        field (set<str>): fields to extract
    Return:
        dict<dict<str>>: the extracted fields for each line
    """
    conversations = []

    with open(fileName, 'r', encoding='iso-8859-1') as f:
        for line in f:
            values = line.split(delimiter)

            # Extract fields
            convObj = {}
            for i, field in enumerate(fields):
                convObj[field] = values[i]

            # Convert string to list (convObj["utteranceIDs"] == "['L598485', 'L598486', ...]")
            lineIds = eval(convObj["utteranceIDs"])

            # Reassemble lines
            convObj["lines"] = []
            for lineId in lineIds:
                convObj["lines"].append(lines[lineId])

            conversations.append(convObj)

    return conversations


def tokenize_conversation(lines):
    sentence_list = [tokenizer(line['text']) for line in lines]
    return sentence_list


if __name__ == '__main__':

    parser = argparse.ArgumentParser()

    # Maximum valid length of sentence
    # => SOS/EOS will surround sentence (EOS for source / SOS for target)
    # => maximum length of tensor = max_sentence_length + 1
    parser.add_argument('-s', '--max_sentence_length', type=int, default=30)
    parser.add_argument('-c', '--max_conversation_length', type=int, default=10)

    # Split Ratio
    split_ratio = [0.8, 0.1, 0.1]

    # Vocabulary
    parser.add_argument('--max_vocab_size', type=int, default=20000)
    parser.add_argument('--min_vocab_frequency', type=int, default=5)

    # Multiprocess
    parser.add_argument('--n_workers', type=int, default=os.cpu_count())

    args = parser.parse_args()

    max_sent_len = args.max_sentence_length
    max_conv_len = args.max_conversation_length
    max_vocab_size = args.max_vocab_size
    min_freq = args.min_vocab_frequency
    n_workers = args.n_workers

    # Download and extract dialogs if necessary.
    prepare_cornell_data()

    print("Loading lines")
    lines = loadLines(cornell_dir.joinpath("movie_lines.txt"))
    print('Number of lines:', len(lines))

    print("Loading conversations...")
    conversations = loadConversations(cornell_dir.joinpath("movie_conversations.txt"), lines)
    print('Number of conversations:', len(conversations))
    print('Train/Valid/Test Split')
    # train, valid, test = train_valid_test_split_by_movie(conversations, split_ratio)

    with open("example.txt", "w") as f:
        f.write("%s\n" % conversations)

    train, valid, test = preprocess_utils.train_valid_test_split_by_conversation(conversations, split_ratio)

    def to_pickle(obj, path):
        with open(path, 'wb') as f:
            pickle.dump(obj, f)

    for split_type, conv_objects in [('train', train), ('valid', valid), ('test', test)]:
        print('Processing', split_type, 'dataset...')
        split_data_dir = cornell_dir.joinpath(split_type)
        split_data_dir.mkdir(exist_ok=True)

        print('Tokenize.. (n_workers=', n_workers, ')')
        def _tokenize_conversation(conv):
            return tokenize_conversation(conv['lines'])
        with Pool(n_workers) as pool:
            conversations = list(tqdm(pool.imap(_tokenize_conversation, conv_objects),
                                     total=len(conv_objects)))

        conversation_length = [min(len(conv['lines']), max_conv_len)
                               for conv in conv_objects]

        sentences, sentence_length = preprocess_utils.pad_sentences(
            conversations,
            max_sentence_length=max_sent_len,
            max_conversation_length=max_conv_len)

        print('Saving preprocessed data at', split_data_dir)
        to_pickle(conversation_length, split_data_dir.joinpath('conversation_length.pkl'))
        to_pickle(sentences, split_data_dir.joinpath('sentences.pkl'))
        to_pickle(sentence_length, split_data_dir.joinpath('sentence_length.pkl'))

        if split_type == 'train':
            print('Save Vocabulary...')
            vocab = Vocab(tokenizer)
            vocab.add_dataframe(conversations)
            vocab.update(max_size=max_vocab_size, min_freq=min_freq)

            print('Vocabulary size: ', len(vocab))
            vocab.pickle(cornell_dir.joinpath('word2id.pkl'), cornell_dir.joinpath('id2word.pkl'))

    print('Done!')
