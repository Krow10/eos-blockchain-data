#!/usr/bin/env python3

"""
SPDX-License-Identifier: MIT
"""

import asyncio
import importlib
import inspect
import logging
from datetime import datetime
from typing import Dict

from dotenv import load_dotenv
from dotenv import find_dotenv

# Load .env before local imports for enabling authentication token queries
load_dotenv(find_dotenv())

#pylint: disable=wrong-import-position
from args import parse_arguments
from block_extractors.async_single_channel_spawner import asyncio_main
from block_extractors.common import process_blocks
from proto import codec_pb2
from utils import get_auth_token
#pylint: enable=wrong-import-position

'''
    TODO
    ====

    - Restructure project with separate "block_streamers" according to each architecture
        - Have a top module main to select which streamer to use
        - Have another file for measuring performance of each streamer
    - Add more examples to README.md
    - Drop the generator requirement for block processors (?)
    - Investigate functools and other more abstract modules for block processor modularity (?)
        - Possibility of 3 stages:
            - Pre-processing (e.g. load some API data)
            - Process (currently implemented)
            - Post-processing (e.g. adding more data to transactions)
'''

CONSOLE_HANDLER = logging.StreamHandler()
JWT = get_auth_token()

def main() -> int:
    """
    Main function for parsing arguments, setting up logging and running asyncio `run` function.
    """
    if not JWT:
        return 1

    logging_handlers = []
    args = parse_arguments()

    # === Arguments checking ===

    if args.end < args.start:
        logging.error('Period start must be less than or equal to period end')
        return 1

    out_file = f'jsonl/{args.chain}_{args.start}_to_{args.end}.jsonl'
    if args.out_file != 'jsonl/{chain}_{start}_to_{end}.jsonl':
        out_file = args.out_file

    log_filename = 'logs/' + datetime.today().strftime('%Y-%m-%d_%H-%M-%S') + '.log'
    if args.log != 'logs/{datetime}.log':
        if args.log:
            log_filename = args.log
        logging_handlers.append(logging.FileHandler(log_filename, mode='a+'))

    CONSOLE_HANDLER.setLevel(logging.INFO)
    if args.quiet:
        CONSOLE_HANDLER.setLevel(logging.ERROR) # Keep only errors and critical messages

    module, function = ('block_processors.default', f'{args.chain}_block_processor')
    if args.custom_processor:
        module, function = args.custom_processor.rsplit('.', 1)
        module = f'block_processors.{module}'

    # === Logging setup ===

    logging_handlers.append(CONSOLE_HANDLER)

    logging.basicConfig(
        handlers=logging_handlers,
        level=logging.DEBUG,
        format='T+%(relativeCreated)d\t%(levelname)s %(message)s',
        force=True
    )

    logging.addLevelName(logging.DEBUG, '[DEBUG]')
    logging.addLevelName(logging.INFO, '[*]')
    logging.addLevelName(logging.WARNING, '[!]')
    logging.addLevelName(logging.ERROR, '[ERROR]')
    logging.addLevelName(logging.CRITICAL, '[CRITICAL]')

    logging.debug('Script arguments: %s', args)

    # === Block processor loading and startup ===

    try:
        block_processor = getattr(importlib.import_module(module), function)

        if not args.disable_signature_check:
            signature = inspect.signature(block_processor)
            parameters_annotations = [p_type.annotation for (_, p_type) in signature.parameters.items()]

            if (signature.return_annotation == signature.empty
                # If there are parameters and none are annotated
                or (not parameters_annotations and signature.parameters)
                # If some parameters are not annotated
                or any((t == inspect.Parameter.empty for t in parameters_annotations))
            ):
                logging.warning('Could not check block processing function signature '
                                '(make sure parameters and return value have type hinting annotations)')
            elif (not codec_pb2.Block in parameters_annotations
                  or signature.return_annotation != Dict
                  or not inspect.isgeneratorfunction(block_processor)
            ):
                raise TypeError(f'Incompatible block processing function signature:'
                                f' {signature} should be <generator>(block: codec_pb2.Block) -> Dict')
    except (AttributeError, TypeError) as exception:
        logging.critical('Could not load block processing function: %s', exception)
        raise
    else:
        return process_blocks(
            asyncio.run(
                asyncio_main(
                    period_start=args.start,
                    period_end=args.end,
                    chain=args.chain,
                    custom_include_expr=args.custom_include_expr,
                    custom_exclude_expr=args.custom_exclude_expr,
                )
            ),
            block_processor=block_processor,
            out_file=out_file,
        )

if __name__ == '__main__':
    main()
