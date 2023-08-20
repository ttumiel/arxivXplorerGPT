import pytest

from xplorer.pdf_paper import PDFPaper


@pytest.mark.parametrize(
    "start,end,text,expected",
    [
        (
            "Start",
            "End",
            "Start\n\nText. Text.\n\nEnd. more text",
            "Text. Text.",
        ),
        (
            "Start",
            None,
            "Start\n\nText. Text.\n\nEnd. more text",
            "Text. Text.\n\nEnd. more text",
        ),
        (
            "Start",
            "End",
            "some text.\n\nA.2. Start\n\nText. Text.\n\nB. End. more text",
            "Text. Text.",
        ),
        (
            "Model Architecture",
            "Why Self-Attention",
            "this is a sentence about the model architecture.\n\n3 Model Architecture\nThe model architecture of the transformer is as follows: ...\n\n4 Why Self-Attention\n\nThe self-attention architecture has 3 main reasons for it's usage here...",
            "The model architecture of the transformer is as follows: ...",
        ),
        (
            "Positional Encoding",
            "Why Self-Attention",
            "\n\n√\n\n3.5 Positional Encoding\n\nSince our model contains no recurrence and no convolution, in order for the model to make use of the\norder of the sequence, we must inject some information about the relative or absolute position of the\n\n5\n\n\x0cTable 1: Maximum path lengths, per-layer complexity and minimum number of sequential operations\nfor different layer types. That is, each dimension of the positional encoding\ncorresponds to a sinusoid. We chose the sinusoidal version\nbecause it may allow the model to extrapolate to sequence lengths longer than the ones encountered\nduring training.\n\n4 Why Self-Attention\n\nIn this section we compare",
            "Since our model contains no recurrence and no convolution, in order for the model to make use of the\norder of the sequence, we must inject some information about the relative or absolute position of the\n\n5\n\n\x0cTable 1: Maximum path lengths, per-layer complexity and minimum number of sequential operations\nfor different layer types. That is, each dimension of the positional encoding\ncorresponds to a sinusoid. We chose the sinusoidal version\nbecause it may allow the model to extrapolate to sequence lengths longer than the ones encountered\nduring training.",
        ),
        (
            "Training",
            "Results",
            "Before the results were finalized we worked on developing the training.\n\n5 Training\n\nThis section describes the training regime for our models.\n\n5.1 Training Data and Batching\n\nWe trained on the standard WMT 2014 English-German dataset consisting of about 4.5 million\nsentence pairs. Sentences were encoded using byte-pair encoding [3], During training, we employed label smoothing of value (cid:15)ls = 0.1 [36]. This\nhurts perplexity, as the model learns to be more unsure, but improves accuracy and BLEU score.\n\n6 Results\n\n6.1 Machine Translation\n\nOn the WMT 2014 English- results...",
            "This section describes the training regime for our models.\n\n5.1 Training Data and Batching\n\nWe trained on the standard WMT 2014 English-German dataset consisting of about 4.5 million\nsentence pairs. Sentences were encoded using byte-pair encoding [3], During training, we employed label smoothing of value (cid:15)ls = 0.1 [36]. This\nhurts perplexity, as the model learns to be more unsure, but improves accuracy and BLEU score.",
        ),
        (
            "Introduction",
            "Adaptive Agent (AdA)",
            "Adaptation in an Open-Ended Task Space\n\n1. Introduction\n\nThe ability to adapt in and\n\ncomplexity of the training task distribution.\n\n• We produce scaling laws in both model size and memory, and demonstrate that AdA improves\n\nits performance with zero-shot ﬁrst-person prompting.\n\n2. Adaptive Agent (AdA)\n\nTo achieve human timescales.",
            "The ability to adapt in and\n\ncomplexity of the training task distribution.\n\n• We produce scaling laws in both model size and memory, and demonstrate that AdA improves\n\nits performance with zero-shot ﬁrst-person prompting.",
        ),
        ("A", "B", "no relevant text here", None),
    ],
)
def test_try_fetch_content(start, end, text, expected):
    result = PDFPaper._try_fetch_content(None, text, start, end)
    assert result == expected


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Introduction", "Introduction"),
        ("3 Introduction", "Introduction"),
        ("3. Introduction", "Introduction"),
        ("3.2.1 Introduction", "Introduction"),
        ("\n\n3.2.1 Introduction \n\n", "Introduction"),
        ("A Introduction", "Introduction"),
        ("A. Introduction", "Introduction"),
        ("B.2 Introduction", "Introduction"),
        ("B.2. Introduction", "Introduction"),
    ],
)
def test_clean_title(title, expected):
    result = PDFPaper._clean_title(None, title)
    assert result == expected
