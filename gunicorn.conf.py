bind = '0.0.0.0:8000'  # Bind to a specific address and port
workers = 2            # Number of worker processes
worker_class = "gthread"
accesslog = '-'        # Log access requests
errorlog = '-'         # Log errors
loglevel = 'info'      
wsgi_app = 'core.wsgi:application'  
