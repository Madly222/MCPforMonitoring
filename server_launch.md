############################
Нужен сервис для автономной работы сервера вот код который нужно записать 
############################

sudo tee /etc/systemd/system/mcp-monitor.service << 'EOF'
[Unit]
Description=MCP Server Monitor
After=network.target

[Service]
Type=simple
User=user
WorkingDirectory=/home/user/ServersMonitoringMCP
Environment="PATH=/home/user/ServersMonitoringMCP/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/home/user/ServersMonitoringMCP/venv/bin/python -m src.main
Restart=always
RestartSec=5
TimeoutStopSec=10
KillMode=mixed

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload

############################
А также вот доступные команды
############################
sudo systemctl daemon-reload
sudo systemctl enable mcp-monitor
sudo systemctl start mcp-monitor
sudo systemctl status mcp-monitor

############################
Что бы добавить почту или изменить адрес для мониторинга отключений воды нужно изменить файл .env
############################

Вот команда nano .env её нужно написать в корне проекта

############################
А вот тут конфиг для адресов которые будут мониторится в Premier energy
############################

Директория /home/user/ServersMonitoringMCP/config название файла electric_addresses.txt

############################
Что бы настроить серверы ссх и другие параметры нужно зайти в файл и по примеру изменить или добавить новые устройства
############################

Вайл называется secrets.yaml и находится в корн проекта



