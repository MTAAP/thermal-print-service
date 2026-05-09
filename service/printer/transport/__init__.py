"""Transport layer: device adapters that the worker calls.

``PrinterUnavailable`` is the contract that lets the worker distinguish
"couldn't open the device" (retryable — printer offline) from "started
writing and failed mid-stream" (not retryable — unknown_partial). It is
NOT an OSError subclass on purpose: the worker catches IOError (= OSError
in Python 3) for the unknown-partial path, so PrinterUnavailable falls
through to the generic Exception branch which retries.
"""


class PrinterUnavailable(Exception):
    """Device couldn't be opened. No bytes were sent to the printer."""
