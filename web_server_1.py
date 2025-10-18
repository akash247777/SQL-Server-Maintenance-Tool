#!/usr/bin/env python3
"""
Web Server for SQL Maintenance Tool
Provides API endpoints for the frontend to interact with the SQL maintenance functionality
"""

import pyodbc
import pandas as pd
import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from contextlib import contextmanager
import sys
import os
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
CORS(app)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Configure for better stability on Windows
app.config['ENV'] = 'development'
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0  # Disable file caching

# Default configuration
DEFAULT_CONFIG = {
    'database': 'POSDBIR',
    'username': 'apposcr',
    'password': '2#06A9a',
    'max_workers': 32,  # Maximum number of worker threads for parallel execution
    # 'query_timeout': 900,  # Removed timeout
    # 'server_timeout': 1800,  # Removed timeout
    # 'connect_timeout': 30  # Removed timeout
}

# Global variables for processing state
processing_state = {
    'is_processing': False,
    'servers': [],
    'results': {},
    'progress': 0,
    'current_server': None,
    'logs': [],
    'start_time': None,
    'config': DEFAULT_CONFIG.copy()
}

# Thread local storage
thread_local = threading.local()

# Lock for thread-safe access to processing_state
processing_state_lock = threading.Lock()

class ServerOfflineError(Exception):
    pass

def vprint(*args, **kwargs):
    """Verbose print function"""
    message = ' '.join(map(str, args))
    logger.info(message)
    processing_state['logs'].append({
        'timestamp': datetime.now().isoformat(),
        'message': message,
        'type': 'info'
    })

def log_message(message, msg_type='info'):
    """Log a message to the processing state"""
    processing_state['logs'].append({
        'timestamp': datetime.now().isoformat(),
        'message': message,
        'type': msg_type
    })

@contextmanager
def suppress_print():
    """Context manager to suppress print output"""
    original_stdout = sys.stdout
    sys.stdout = open(os.devnull, 'w')
    try:
        yield
    finally:
        sys.stdout.close()
        sys.stdout = original_stdout

def get_connection(server, config):
    """Get or create a database connection for a server (no timeout)"""
    conn_key = f"conn_{server}"
    if hasattr(thread_local, conn_key):
        conn = getattr(thread_local, conn_key)
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            return conn
        except:
            delattr(thread_local, conn_key)
    conn_str = f'DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};DATABASE={config["database"]};UID={config["username"]};PWD={config["password"]};autocommit=True'
    try:
        new_conn = pyodbc.connect(conn_str)
    except Exception as e:
        error_msg = str(e)
        if "could not open a connection to sql server" in error_msg.lower():
            raise ServerOfflineError(f"Could not open connection to SQL Server: {error_msg}")
        elif "server was not found" in error_msg.lower():
            raise ServerOfflineError(f"Server not found or not accessible: {error_msg}")
        elif "login failed" in error_msg.lower():
            raise ServerOfflineError(f"Login failed for server: {error_msg}")
        else:
            raise ServerOfflineError(f"Connection error: {error_msg}")
    setattr(thread_local, conn_key, new_conn)
    return new_conn

def execute_statement(server, stmt, stmt_index, total_stmts, config):
    """Execute a single statement with progress tracking"""
    try:
        conn = get_connection(server, config)
        with conn.cursor() as cursor:
            start = time.time()
            cursor.execute(stmt)
            elapsed = time.time() - start
        
        message = f"[{server}] [{stmt_index}/{total_stmts}] Success ({elapsed:.2f}s): {stmt[:80]}..."
        log_message(message, 'success')
        
        return {
            'success': True,
            'index': stmt_index,
            'statement': stmt,
            'time': elapsed,
            'message': message
        }
    except Exception as e:
        message = f"[{server}] [{stmt_index}/{total_stmts}] Error: {stmt[:80]}... - {str(e)}"
        log_message(message, 'error')
        
        return {
            'success': False,
            'index': stmt_index,
            'statement': stmt,
            'time': 0,
            'message': message
        }

def batch_and_execute_optimized(server, statements, label, config):
    """Execute statements in parallel with progress tracking"""
    log_message(f"\n[{server}] Executing {len(statements)} {label} statements...", 'info')
    start = time.time()

    success_count = 0
    error_count = 0
    results = []

    with ThreadPoolExecutor(max_workers=min(len(statements), config.get('max_workers', 32))) as executor:
        futures = {executor.submit(execute_statement, server, stmt, idx+1, len(statements), config): idx 
                  for idx, stmt in enumerate(statements)}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            if result['success']:
                success_count += 1
            else:
                error_count += 1

    # After all statements are executed, print/log all results
    for result in results:
        log_message(result['message'], 'success' if result['success'] else 'error')

    elapsed = time.time() - start
    log_message(f"[{server}] {label} completed: {success_count} succeeded, {error_count} failed in {elapsed:.2f} seconds", 'info')
    return success_count, error_count

def get_database_size(server, cursor, config):
    """Get database size"""
    try:
        cursor.execute(f"""
            SELECT 
                SUM(size) * 8 AS size_kb
            FROM sys.master_files 
            WHERE database_id = DB_ID('{config["database"]}') AND type_desc = 'ROWS'
        """)
        row = cursor.fetchone()
        if row and row[0]:
            return int(row[0])
    except Exception as e:
        log_message(f"[{server}] Error getting database size: {e}", 'error')
    
    # Fallback method
    try:
        cursor.execute("exec sp_helpfile")
        rows = cursor.fetchall()
        total_size = 0
        for row in rows:
            try:
                size_str = str(row[4]).strip()
                if size_str.endswith('KB'):
                    size_kb = int(size_str.replace('KB', '').replace(' ', ''))
                elif size_str.endswith('MB'):
                    size_kb = int(float(size_str.replace('MB', '').replace(' ', '')) * 1024)
                elif size_str.endswith('GB'):
                    size_kb = int(float(size_str.replace('GB', '').replace(' ', '')) * 1024 * 1024)
                else:
                    size_kb = int(size_str)
                total_size += size_kb
            except:
                continue
        if total_size > 0:
            return total_size
    except Exception as e:
        log_message(f"[{server}] Error in fallback size method: {e}", 'error')
    
    return None

def check_compression_status(server, cursor):
    """Check if compression is enabled on tables and indexes"""
    try:
        cursor.execute("""
            SELECT 
                t.name AS table_name,
                i.name AS index_name,
                p.data_compression_desc
            FROM sys.tables t
            INNER JOIN sys.partitions p ON t.object_id = p.object_id
            LEFT JOIN sys.indexes i ON p.object_id = i.object_id AND p.index_id = i.index_id
            WHERE p.data_compression > 0
        """)
        compressed_objects = cursor.fetchall()
        compressed_count = len(compressed_objects)
        log_message(f"[{server}] Found {compressed_count} compressed objects", 'info')
        return compressed_count > 0
    except Exception as e:
        log_message(f"[{server}] Error checking compression status: {e}", 'error')
        return False

def stop_asyncnew_service(server, config):
    """Stop AsyncNew service before processing (no timeout)"""
    log_message(f"[{server}] Stopping AsyncNew service...", 'info')
    conn_str = f'DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};DATABASE={config["database"]};UID={config["username"]};PWD={config["password"]};autocommit=True'

    try:
        with pyodbc.connect(conn_str, autocommit=True) as conn:
            with conn.cursor() as cursor:
                # Stop service sequence
                log_message(f"[{server}] Enabling advanced options...", 'info')
                cursor.execute("EXEC sp_configure 'show advanced options', 1")
                cursor.execute("RECONFIGURE")
                
                log_message(f"[{server}] Enabling xp_cmdshell...", 'info')
                cursor.execute("EXEC sp_configure 'xp_cmdshell', 1")
                cursor.execute("RECONFIGURE")
                
                log_message(f"[{server}] Stopping AsyncNew service...", 'info')
                cursor.execute("EXEC xp_cmdshell 'net stop AsyncNew'")
                cursor.fetchall()  # Consume results
                
                log_message(f"[{server}] Disabling xp_cmdshell...", 'info')
                cursor.execute("EXEC sp_configure 'xp_cmdshell', 0")
                cursor.execute("RECONFIGURE")
                
                log_message(f"[{server}] Disabling advanced options...", 'info')
                cursor.execute("EXEC sp_configure 'show advanced options', 0")
                cursor.execute("RECONFIGURE")
        
        log_message(f"[{server}] AsyncNew service stopped successfully.", 'success')
        return True
    except Exception as e:
        log_message(f"[{server}] Error stopping AsyncNew service: {e}", 'error')
        if "could not open a connection" in str(e).lower() or "server was not found" in str(e).lower():
            log_message(f"[{server}] Connection error - skipping service stop", 'warning')
        return False

def start_asyncnew_service(server, config):
    """Start AsyncNew service after processing (no timeout)"""
    log_message(f"[{server}] Starting AsyncNew service...", 'info')
    conn_str = f'DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};DATABASE={config["database"]};UID={config["username"]};PWD={config["password"]};autocommit=True'

    try:
        with pyodbc.connect(conn_str, autocommit=True) as conn:
            with conn.cursor() as cursor:
                # Start service sequence
                log_message(f"[{server}] Enabling advanced options...", 'info')
                cursor.execute("EXEC sp_configure 'show advanced options', 1")
                cursor.execute("RECONFIGURE")
                
                log_message(f"[{server}] Enabling xp_cmdshell...", 'info')
                cursor.execute("EXEC sp_configure 'xp_cmdshell', 1")
                cursor.execute("RECONFIGURE")
                
                log_message(f"[{server}] Starting AsyncNew service...", 'info')
                cursor.execute("EXEC xp_cmdshell 'net start AsyncNew'")
                cursor.fetchall()  # Consume results
                
                log_message(f"[{server}] Disabling xp_cmdshell...", 'info')
                cursor.execute("EXEC sp_configure 'xp_cmdshell', 0")
                cursor.execute("RECONFIGURE")
                
                log_message(f"[{server}] Disabling advanced options...", 'info')
                cursor.execute("EXEC sp_configure 'show advanced options', 0")
                cursor.execute("RECONFIGURE")
        
        log_message(f"[{server}] AsyncNew service started successfully.", 'success')
        return True
    except Exception as e:
        log_message(f"[{server}] Error starting AsyncNew service: {e}", 'error')
        if "could not open a connection" in str(e).lower() or "server was not found" in str(e).lower():
            log_message(f"[{server}] Connection error - skipping service start", 'warning')
        return False

def run_posdbshrink(server, config):
    """Execute POSDBSHRINK with improved error handling (no timeout)"""
    log_message(f"[{server}] Executing POSDBSHRINK...", 'info')
    conn_str = f'DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};DATABASE={config["database"]};UID={config["username"]};PWD={config["password"]};autocommit=True'

    try:
        with pyodbc.connect(conn_str, autocommit=True) as conn:
            with conn.cursor() as cursor:
                log_message(f"[{server}] Running POSDBSHRINK...", 'info')
                cursor.execute("EXEC POSDBSHRINK")
                while True:
                    if cursor.description:
                        columns = [col[0] for col in cursor.description]
                        for row in cursor.fetchall():
                            log_message(f"[{server}] POSDBSHRINK result: {dict(zip(columns, row))}", 'info')
                    if not cursor.nextset():
                        break
        
        log_message(f"[{server}] POSDBSHRINK executed successfully.", 'success')
        return True
    except Exception as e:
        log_message(f"[{server}] POSDBSHRINK error: {e}", 'error')
        return False

def process_server(server, config):
    """Process a single server with the SQL maintenance operations"""
    initial_size = final_size = None
    start_time = time.time()
    conn = None
    # Track AsyncNew stop/start attempts and success
    stop_attempted = False
    start_attempted = False
    stop_success = False
    start_success = False
    
    try:
        processing_state['current_server'] = server
        log_message(f"\n[{server}] Starting operations...", 'info')
        
        # Try to connect - if fails, skip this server immediately
        try:
            conn = get_connection(server, config)
            cursor = conn.cursor()
        except ServerOfflineError as conn_error:
            log_message(f"[{server}] Connection failed: {conn_error}", 'error')
            log_message(f"[{server}] Skipping server due to connection error", 'warning')
            return {
                'status': 'CONNECTION_FAILED',
                'initial_size': None,
                'final_size': None,
                'duration': time.time() - start_time,
                'error': str(conn_error),
                'stopped_asyncnew': False,
                'started_asyncnew': False
            }

        # Initial size check
        log_message(f"[{server}] Checking initial database size...", 'info')
        initial_size = get_database_size(server, cursor, config)
        log_message(f"[{server}] After initial size check", 'debug')
        if initial_size:
            log_message(f"[{server}] Initial DB size: {initial_size} KB ({initial_size / 1024 / 1024:.2f} GB)", 'info')

        # Check current compression status
        log_message(f"[{server}] Checking current compression status...", 'info')
        check_compression_status(server, cursor)
        log_message(f"[{server}] After compression status check", 'debug')

        # Stop AsyncNew service before processing
        cursor.close()
        conn.close()
        time.sleep(1)

        log_message(f"[{server}] Stopping AsyncNew service before processing...", 'info')
        stop_attempted = True
        stop_success = stop_asyncnew_service(server, config)
        log_message(f"[{server}] After stop_asyncnew_service", 'debug')
        if not stop_success:
            log_message(f"[{server}] Warning: Failed to stop AsyncNew service", 'warning')
        # Publish stop result immediately so UI can reflect it
        try:
            with processing_state_lock:
                # Only update if there's already an entry for this server
                # Don't create a new entry as that would make the frontend think processing is done
                if server in processing_state['results']:
                    existing = processing_state['results'][server]
                    existing['stopped_asyncnew'] = bool(stop_success)
                    existing['stopped_asyncnew_attempted'] = True
                # Don't create a new entry - that would cause the frontend to think the server is done
        except Exception as ex:
            log_message(f"[{server}] Exception updating stopped_asyncnew: {ex}", 'error')

        # Reconnect after service stop - handle connection errors
        time.sleep(1)
        try:
            conn = get_connection(server, config)
            cursor = conn.cursor()
            log_message(f"[{server}] After reconnect post stop_asyncnew_service", 'debug')
        except ServerOfflineError as conn_error:
            log_message(f"[{server}] Reconnection failed after service stop: {conn_error}", 'error')
            log_message(f"[{server}] Skipping server due to connection error", 'warning')
            return {
                'status': 'CONNECTION_FAILED',
                'initial_size': initial_size,
                'final_size': None,
                'duration': time.time() - start_time,
                'error': str(conn_error),
                'stopped_asyncnew': bool(stop_success),
                'stopped_asyncnew_attempted': bool(stop_attempted),
                'started_asyncnew': False,
                'started_asyncnew_attempted': False
            }

        # Optimized query to fetch metadata
        log_message(f"[{server}] Fetching table and index metadata...", 'info')
        try:
            cursor.execute("""
            SET NOCOUNT ON;
            SELECT 
                s.name AS schema_name,
                o.name AS object_name,
                i.name AS index_name,
                i.index_id,
                o.object_id,
                ps.reserved_page_count
            FROM sys.objects o
            JOIN sys.indexes i ON o.object_id = i.object_id
            JOIN sys.schemas s ON o.schema_id = s.schema_id
            JOIN sys.dm_db_partition_stats ps ON i.object_id = ps.object_id AND ps.index_id = i.index_id
            WHERE o.type = 'U' AND i.index_id >= 0
            ORDER BY ps.reserved_page_count DESC
            """)
            rows = cursor.fetchall()
            log_message(f"[{server}] Found {len(rows)} tables/indexes across database", 'info')
        except Exception as ex:
            log_message(f"[{server}] Exception during metadata fetch: {ex}", 'error')
            rows = []

        object_id_to_schema_table = {}
        seen_tables = set()
        seen_indexes = set()

        # Initialize statement lists
        alter_index_statements = []
        alter_table_statements = []

        for row in rows:
            schema_name, object_name, index_name, index_id, object_id, page_count = row

            # Store object_id and table info for later
            if object_id not in seen_tables:
                object_id_to_schema_table[object_id] = (schema_name, object_name)
                seen_tables.add(object_id)

            # ALTER INDEX statements for indexes (index_id > 0)
            if index_name and index_id > 0:
                index_key = f"{schema_name}.{object_name}.{index_name}"
                if index_key not in seen_indexes:
                    stmt = f'ALTER INDEX [{index_name}] ON [{schema_name}].[{object_name}] REBUILD WITH (DATA_COMPRESSION=PAGE, MAXDOP=1);'
                    alter_index_statements.append(stmt)
                    seen_indexes.add(index_key)

        # Generate ALTER TABLE statements (one per table including heaps)
        for object_id in seen_tables:
            schema_name, object_name = object_id_to_schema_table[object_id]
            stmt = f'ALTER TABLE [{schema_name}].[{object_name}] REBUILD WITH (DATA_COMPRESSION=PAGE, MAXDOP=1);'
            alter_table_statements.append(stmt)

        log_message(f"[{server}] Generated {len(alter_index_statements)} ALTER INDEX statements", 'info')
        log_message(f"[{server}] Generated {len(alter_table_statements)} ALTER TABLE statements", 'info')
        log_message(f"[{server}] After statement generation", 'debug')

        # Execute ALTER INDEX statements
        if alter_index_statements:
            log_message(f"[{server}] Executing ALTER INDEX statements...", 'info')
            try:
                success_count, error_count = batch_and_execute_optimized(server, alter_index_statements, "ALTER INDEX", config)
                log_message(f"[{server}] After ALTER INDEX execution", 'debug')
                if error_count > 0:
                    log_message(f"[{server}] Warning: {error_count} ALTER INDEX statements failed", 'warning')
            except Exception as ex:
                log_message(f"[{server}] Exception during ALTER INDEX execution: {ex}", 'error')
        else:
            log_message(f"[{server}] No ALTER INDEX statements to execute", 'info')

        # Execute ALTER TABLE statements
        if alter_table_statements:
            log_message(f"[{server}] Executing ALTER TABLE statements...", 'info')
            try:
                success_count, error_count = batch_and_execute_optimized(server, alter_table_statements, "ALTER TABLE", config)
                log_message(f"[{server}] After ALTER TABLE execution", 'debug')
                if error_count > 0:
                    log_message(f"[{server}] Warning: {error_count} ALTER TABLE statements failed", 'warning')
            except Exception as ex:
                log_message(f"[{server}] Exception during ALTER TABLE execution: {ex}", 'error')
        else:
            log_message(f"[{server}] No ALTER TABLE statements to execute", 'info')

        # Run POSDBSHRINK multiple times
        try:
            cursor.close()
            conn.close()
        except Exception as ex:
            log_message(f"[{server}] Exception closing cursor/conn before POSDBSHRINK: {ex}", 'error')
        time.sleep(1)

        log_message(f"[{server}] Running POSDBSHRINK for size reduction...", 'info')
        log_message(f"[{server}] POSDBSHRINK attempt 1/1...", 'info')
        try:
            success = run_posdbshrink(server, config)
            log_message(f"[{server}] After POSDBSHRINK attempt 1", 'debug')
            if not success:
                log_message(f"[{server}] POSDBSHRINK attempt 1 failed", 'error')
        except Exception as ex:
            log_message(f"[{server}] Exception during POSDBSHRINK attempt 1: {ex}", 'error')
        time.sleep(1)

        # Reconnect for remaining operations - handle connection errors
        try:
            conn = get_connection(server, config)
            cursor = conn.cursor()
            log_message(f"[{server}] After reconnect post POSDBSHRINK", 'debug')
        except ServerOfflineError as conn_error:
            log_message(f"[{server}] Reconnection failed after POSDBSHRINK: {conn_error}", 'error')
            log_message(f"[{server}] Skipping server due to connection error", 'warning')
            return {
                'status': 'CONNECTION_FAILED',
                'initial_size': initial_size,
                'final_size': None,
                'duration': time.time() - start_time,
                'error': str(conn_error),
                'stopped_asyncnew': bool(stop_success),
                'started_asyncnew': False
            }

        # Check compression status after operations
        log_message(f"[{server}] Verifying compression status after operations...", 'info')
        try:
            check_compression_status(server, cursor)
            log_message(f"[{server}] After compression status check post operations", 'debug')
        except Exception as ex:
            log_message(f"[{server}] Exception during compression status check post operations: {ex}", 'error')

        # Generate UPDATE STATISTICS statements
        log_message(f"[{server}] Generating UPDATE STATISTICS statements...", 'info')
        stats_statements = []
        seen_stats_tables = set()

        for object_id in seen_tables:
            schema_name, object_name = object_id_to_schema_table[object_id]
            table_key = f"{schema_name}.{object_name}"
            if table_key not in seen_stats_tables:
                stmt = f'UPDATE STATISTICS [{schema_name}].[{object_name}] WITH FULLSCAN;'
                stats_statements.append(stmt)
                seen_stats_tables.add(table_key)

        log_message(f"[{server}] Generated {len(stats_statements)} UPDATE STATISTICS statements", 'info')
        log_message(f"[{server}] After UPDATE STATISTICS statement generation", 'debug')

        # Execute UPDATE STATISTICS statements
        if stats_statements:
            try:
                success_count, error_count = batch_and_execute_optimized(server, stats_statements, "UPDATE STATISTICS", config)
                log_message(f"[{server}] After UPDATE STATISTICS execution", 'debug')
                if error_count > 0:
                    log_message(f"[{server}] Warning: {error_count} UPDATE STATISTICS statements failed", 'warning')
            except Exception as ex:
                log_message(f"[{server}] Exception during UPDATE STATISTICS execution: {ex}", 'error')
        else:
            log_message(f"[{server}] No UPDATE STATISTICS statements to execute", 'info')

        # Final size check
        log_message(f"[{server}] Checking final database size...", 'info')
        try:
            final_size = get_database_size(server, cursor, config)
            log_message(f"[{server}] After final size check", 'debug')
            if final_size:
                log_message(f"[{server}] Final DB size: {final_size} KB ({final_size / 1024 / 1024:.2f} GB)", 'info')
                if initial_size:
                    reduction = initial_size - final_size
                    reduction_pct = (reduction / initial_size) * 100 if initial_size > 0 else 0
                    log_message(f"[{server}] Size reduced by {reduction} KB ({reduction / 1024 / 1024:.2f} GB) - {reduction_pct:.2f}%", 'success')
            else:
                log_message(f"[{server}] Could not determine final database size", 'warning')
        except Exception as ex:
            log_message(f"[{server}] Exception during final size check: {ex}", 'error')

        # Start AsyncNew service after processing
        try:
            cursor.close()
            conn.close()
        except Exception as ex:
            log_message(f"[{server}] Exception closing cursor/conn before start_asyncnew_service: {ex}", 'error')
        time.sleep(1)

        log_message(f"[{server}] Starting AsyncNew service after processing...", 'info')
        start_attempted = True
        try:
            start_success = start_asyncnew_service(server, config)
            log_message(f"[{server}] After start_asyncnew_service", 'debug')
            if not start_success:
                log_message(f"[{server}] Warning: Failed to start AsyncNew service", 'warning')
        except Exception as ex:
            start_success = False
            log_message(f"[{server}] Exception during start_asyncnew_service: {ex}", 'error')
        # Publish start result immediately so UI can reflect it
        try:
            with processing_state_lock:
                # Only update if there's already an entry for this server
                # Don't create a new entry as that would make the frontend think processing is done
                if server in processing_state['results']:
                    existing = processing_state['results'][server]
                    existing['started_asyncnew'] = bool(start_success)
                    existing['started_asyncnew_attempted'] = True
                # Don't create a new entry - that would cause the frontend to think the server is done
        except Exception as ex:
            log_message(f"[{server}] Exception updating started_asyncnew: {ex}", 'error')

        log_message(f"[{server}] Returning SUCCESS result", 'debug')
        return {
            'status': 'SUCCESS',
            'initial_size': initial_size,
            'final_size': final_size,
            'duration': time.time() - start_time,
            'stopped_asyncnew': bool(stop_success),
            'stopped_asyncnew_attempted': bool(stop_attempted),
            'started_asyncnew': bool(start_success),
            'started_asyncnew_attempted': bool(start_attempted)
        }
        
    except Exception as e:
        log_message(f"[{server}] Error: {e}", 'error')
        import traceback
        log_message(f"[{server}] Traceback: {traceback.format_exc()}", 'error')
        
        # Ensure service is started even if there's an error
        try:
            if conn:
                conn.close()
            time.sleep(1)
            log_message(f"[{server}] Attempting to start AsyncNew service after error...", 'info')
            restart_success = start_asyncnew_service(server, config)
        except Exception as service_error:
            restart_success = False
            log_message(f"[{server}] Error starting service after failure: {service_error}", 'error')
        
        return {
            'status': 'FAILED',
            'initial_size': initial_size,
            'final_size': final_size,
            'duration': time.time() - start_time,
            'error': str(e),
            'stopped_asyncnew': bool(stop_success),
            'stopped_asyncnew_attempted': bool(stop_attempted),
            'started_asyncnew': bool(restart_success),
            'started_asyncnew_attempted': bool(start_attempted)
        }
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass
        processing_state['current_server'] = None

def process_servers_async(servers):
    """Process servers asynchronously"""
    global processing_state
    
    # Use default configuration
    config = DEFAULT_CONFIG.copy()
    
    # Thread-safe access to processing_state
    with processing_state_lock:
        processing_state.update({
            'is_processing': True,
            'servers': servers,
            'results': {},
            'progress': 0,
            'logs': [],
            'start_time': time.time(),
            'end_time': None,
            'config': config
        })
    
    # Handle empty server list
    if not servers:
        log_message("No servers to process, setting is_processing to False", 'warning')
        with processing_state_lock:
            processing_state['is_processing'] = False
        return
    
    log_message("Starting SQL maintenance...", 'info')
    # log_message(f"Query timeout: {config['query_timeout']} seconds", 'info')
    # log_message(f"Server timeout: {config['server_timeout']} seconds", 'info')
    
    try:
        # Use ThreadPoolExecutor for parallel processing
        # Set max_workers to the number of servers for true parallel execution
        max_workers = min(len(servers), config.get('max_workers', 100))  # Use config value, cap at 100 to prevent resource exhaustion
        log_message(f"Starting parallel processing of {len(servers)} servers with {max_workers} worker threads", 'info')
        try:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_server = {executor.submit(process_server, server, config): server for server in servers}
                log_message(f"All {len(servers)} servers submitted for parallel processing", 'success')
                for future in as_completed(future_to_server):
                    server = future_to_server[future]
                    try:
                        result = future.result()  # No timeout
                        result.setdefault('stopped_asyncnew', False)
                        result.setdefault('started_asyncnew', False)
                        with processing_state_lock:
                            processing_state['results'][server] = result
                        if result['status'] == 'CONNECTION_FAILED':
                            log_message(f"[{server}] Connection failed - server skipped", 'warning')
                        else:
                            log_message(f"[{server}] Parallel processing completed successfully", 'success')
                    except Exception as e:
                        error_msg = str(e)
                        if "connection" in error_msg.lower() or "server" in error_msg.lower():
                            log_message(f"[{server}] Connection error during processing: {error_msg}", 'error')
                            with processing_state_lock:
                                processing_state['results'][server] = {
                                    'status': 'CONNECTION_FAILED',
                                    'initial_size': None,
                                    'final_size': None,
                                    'duration': 0,
                                    'error': error_msg,
                                    'stopped_asyncnew': False,
                                    'stopped_asyncnew_attempted': False,
                                    'started_asyncnew': False,
                                    'started_asyncnew_attempted': False
                                }
                        else:
                            log_message(f"[{server}] Exception during parallel processing: {error_msg}", 'error')
                            with processing_state_lock:
                                processing_state['results'][server] = {
                                    'status': 'FAILED',
                                    'initial_size': None,
                                    'final_size': None,
                                    'duration': 0,
                                    'error': error_msg,
                                    'stopped_asyncnew': False,
                                    'stopped_asyncnew_attempted': False,
                                    'started_asyncnew': False,
                                    'started_asyncnew_attempted': False
                                }
                    with processing_state_lock:
                        # Count only servers that have actually completed (have a status field)
                        completed_count = sum(1 for result in processing_state['results'].values() if 'status' in result)
                        if len(servers) > 0:
                            processing_state['progress'] = (completed_count / len(servers)) * 100
                        else:
                            processing_state['progress'] = 100
                        log_message(f"Parallel processing progress: {completed_count}/{len(servers)} servers completed ({processing_state['progress']:.1f}%)", 'info')
                        if completed_count >= len(servers):
                            log_message(f"All servers processed, setting is_processing to False", 'info')
                            processing_state['is_processing'] = False
                        log_message(f"Current state: {completed_count}/{len(servers)} completed, is_processing={processing_state['is_processing']}", 'info')
        except Exception as executor_error:
            log_message(f"Error with ThreadPoolExecutor: {executor_error}", 'error')
            with processing_state_lock:
                processing_state['is_processing'] = False
        
        # Final summary
        log_message("\n" + "=" * 70, 'info')
        log_message("SUMMARY OF SERVER OPERATIONS", 'info')
        log_message("=" * 70, 'info')
        
        # Ensure is_processing is set to False when all servers are processed
        with processing_state_lock:
            processing_state['is_processing'] = False
        
        for server in servers:
            status = processing_state['results'].get(server, {}).get('status', 'FAILED')
            log_message(f"{server}: {status}", 'info')

        log_message("\n" + "-" * 70, 'info')
        log_message("SIZE COMPARISON BY SERVER", 'info')
        log_message("-" * 70, 'info')
        
        for server in servers:
            result = processing_state['results'].get(server, {})
            status = result.get('status')
            initial_size = result.get('initial_size')
            final_size = result.get('final_size')
            
            if status == 'TIMEOUT':
                log_message(f"{server}: TIMEOUT - server took too long, comparison unavailable", 'warning')
            elif initial_size is not None and final_size is not None:
                reduction_kb = initial_size - final_size
                reduction_gb = reduction_kb / 1024 / 1024
                reduction_pct = ((reduction_kb / initial_size) * 100) if initial_size and initial_size > 0 else 0
                log_message(f"{server}: Before {config['database']} - {initial_size} KB ({initial_size/1024/1024:.2f} GB)", 'info')
                log_message(f"{server}: After - {final_size} KB ({final_size/1024/1024:.2f} GB)", 'info')
                log_message(f"{server}: Reduced {reduction_kb} KB ({reduction_gb:.2f} GB) - {reduction_pct:.2f}%", 'success')
            else:
                log_message(f"{server}: Comparison unavailable", 'warning')

        total_time = time.time() - processing_state['start_time']
        log_message(f"\n{'=' * 70}", 'info')
        log_message(f"PARALLEL PROCESSING COMPLETED", 'success')
        log_message(f"Overall execution time: {total_time:.2f} seconds ({total_time / 60:.2f} minutes)", 'info')
        log_message(f"Servers processed in parallel: {len(servers)}", 'info')
        log_message(f"Average time per server: {total_time / len(servers):.2f} seconds", 'info')
        log_message("=" * 70, 'info')
        
    except Exception as e:
        log_message(f"Error in processing: {e}", 'error')
        # Ensure is_processing is set to False even if there's an exception
        with processing_state_lock:
            processing_state['is_processing'] = False
    finally:
        with processing_state_lock:
            processing_state['is_processing'] = False
            processing_state['end_time'] = time.time()
        log_message("Processing completed, is_processing set to False and end_time recorded in finally block", 'info')

def read_excel_servers(file_path):
    """Read server names and size data from Excel file"""
    try:
        # Read the Excel file
        df = pd.read_excel(file_path)
        
        if len(df.columns) == 0:
            raise ValueError("Excel file has no columns")
        
        # Get server names from the first column
        servers = df.iloc[:, 0].dropna().astype(str).tolist()
        
        # Extract size data if available
        size_data = {}
        
        # Look for common column names for size data
        column_mapping = {
            'initial_size': ['Initial Size (GB)', 'Initial Size', 'InitialSize', 'Initial_Size'],
            'final_size': ['Final Size (GB)', 'Final Size', 'FinalSize', 'Final_Size'],
            'space_saved': ['Space Saved (GB)', 'Space Saved', 'SpaceSaved', 'Space_Saved'],
            'reduction_percent': ['Reduction %', 'Reduction', 'ReductionPercent', 'Reduction_Percent']
        }
        
        # Find matching columns
        for key, possible_names in column_mapping.items():
            for col_name in possible_names:
                if col_name in df.columns:
                    size_data[key] = df[col_name].fillna(0).tolist()
                    logger.info(f"Found column '{col_name}' for {key}")
                    break
        
        # Create server data with size information
        server_data = []
        for i, server in enumerate(servers):
            server_info = {
                'name': server,
                'initial_size': size_data.get('initial_size', [None] * len(servers))[i] if i < len(size_data.get('initial_size', [])) else None,
                'final_size': size_data.get('final_size', [None] * len(servers))[i] if i < len(size_data.get('final_size', [])) else None,
                'space_saved': size_data.get('space_saved', [None] * len(servers))[i] if i < len(size_data.get('space_saved', [])) else None,
                'reduction_percent': size_data.get('reduction_percent', [None] * len(servers))[i] if i < len(size_data.get('reduction_percent', [])) else None
            }
            server_data.append(server_info)
        
        logger.info(f"Parsed {len(servers)} servers with size data: {bool(size_data)}")
        return server_data
            
    except Exception as e:
        logger.error(f"Error reading Excel file: {e}")
        raise

# Flask Routes

@app.route('/')
def index():
    """Serve the main HTML page"""
    return send_from_directory('.', 'index.html')

@app.route('/styles.css')
def styles():
    """Serve the CSS file"""
    return send_from_directory('.', 'styles.css')

@app.route('/script.js')
def script():
    """Serve the JavaScript file"""
    return send_from_directory('.', 'script.js')

@app.route('/api/upload', methods=['POST'])
def upload_file():
    """Handle file upload and extract server names"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        if file.filename == '' or file.filename is None:
            return jsonify({'error': 'No file selected'}), 400
        
        # Save uploaded file temporarily
        filename = secure_filename(file.filename)
        file_path = os.path.join('/tmp', filename)
        file.save(file_path)
        
        # Read server data from Excel
        server_data = read_excel_servers(file_path)
        
        # Clean up temporary file
        os.remove(file_path)
        
        # Extract just server names for backward compatibility
        servers = [server['name'] for server in server_data]
        
        return jsonify({
            'success': True,
            'servers': servers,
            'server_data': server_data,
            'count': len(servers),
            'has_size_data': any(server.get('initial_size') is not None or 
                                server.get('final_size') is not None or 
                                server.get('space_saved') is not None or 
                                server.get('reduction_percent') is not None 
                                for server in server_data)
        })
        
    except Exception as e:
        logger.error(f"Error uploading file: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/process', methods=['POST'])
def start_processing():
    """Start processing servers"""
    try:
        data = request.get_json()
        servers = data.get('servers', [])
        server_data = data.get('server_data', [])
        
        if not servers:
            return jsonify({'error': 'No servers provided'}), 400
        
        # Thread-safe access to processing_state
        with processing_state_lock:
            if processing_state['is_processing']:
                return jsonify({'error': 'Processing already in progress'}), 400
        
        # Store server data in processing state for reference
        with processing_state_lock:
            processing_state['server_data'] = server_data
        
        # Start processing in a separate thread
        thread = threading.Thread(target=process_servers_async, args=(servers,))
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'message': 'Processing started',
            'server_count': len(servers)
        })
        
    except Exception as e:
        logger.error(f"Error starting processing: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/status', methods=['GET'])
def get_status():
    """Get current processing status"""
    try:
        # Thread-safe access to processing_state
        with processing_state_lock:
            return jsonify({
                'is_processing': processing_state['is_processing'],
                'progress': processing_state['progress'],
                'current_server': processing_state['current_server'],
                'servers': processing_state['servers'],
                'server_data': processing_state.get('server_data', []),
                'results': processing_state['results'],
                'logs': processing_state['logs'][-100:],  # Last 100 log entries
                'start_time': processing_state['start_time']
            })
        
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/results', methods=['GET'])
def get_results():
    """Get final results"""
    try:
        # Thread-safe access to processing_state
        with processing_state_lock:
            return jsonify({
                'results': processing_state['results'],
                'servers': processing_state['servers'],
                'server_data': processing_state.get('server_data', []),
                'logs': processing_state['logs'],
                'start_time': processing_state['start_time'],
                'end_time': time.time() if not processing_state['is_processing'] else None
            })
        
    except Exception as e:
        logger.error(f"Error getting results: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/stop', methods=['POST'])
def stop_processing():
    """Stop current processing"""
    try:
        # Thread-safe access to processing_state
        with processing_state_lock:
            processing_state['is_processing'] = False
        log_message("Processing stopped by user request", 'warning')
        
        return jsonify({
            'success': True,
            'message': 'Processing stopped'
        })
        
    except Exception as e:
        logger.error(f"Error stopping processing: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/config', methods=['GET'])
def get_config():
    """Get current configuration"""
    try:
        # Thread-safe access to processing_state
        with processing_state_lock:
            return jsonify({
                'success': True,
                'config': processing_state['config']
            })
        
    except Exception as e:
        logger.error(f"Error getting configuration: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/config', methods=['POST'])
def update_config():
    """Update configuration"""
    try:
        # Thread-safe access to processing_state
        with processing_state_lock:
            if processing_state['is_processing']:
                return jsonify({'error': 'Cannot update configuration while processing'}), 400
        
        data = request.get_json()
        
        # Update only provided configuration values
        for key, value in data.items():
            if key in DEFAULT_CONFIG:
                with processing_state_lock:
                    processing_state['config'][key] = value
        
        log_message("Configuration updated", 'info')
        
        # Thread-safe access to processing_state
        with processing_state_lock:
            return jsonify({
                'success': True,
                'message': 'Configuration updated',
                'config': processing_state['config']
            })
        
    except Exception as e:
        logger.error(f"Error updating configuration: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # Create temp directory if it doesn't exist
    os.makedirs('/tmp', exist_ok=True)
    
    print("Starting SQL Maintenance Tool Web Server...")
    print("Open your browser and navigate to: http://localhost:5000")
    
    # Use a more robust server configuration to avoid socket errors on Windows
    # Disable reloader to prevent socket issues on Windows during development
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False, threaded=True)
