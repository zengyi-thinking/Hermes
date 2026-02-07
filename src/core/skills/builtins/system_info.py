"""
系统信息技能
"""

import platform
from typing import Any, Dict
from ..base import Skill, SkillResult


class SystemInfoSkill(Skill):
    """系统信息技能"""

    name = "system_info"
    description = "获取系统信息，如 CPU、内存、磁盘使用情况"
    permission_level = "normal"

    async def execute(
        self,
        info_type: str = "all",
        **kwargs
    ) -> SkillResult:
        """
        获取系统信息

        Args:
            info_type: 信息类型 (all, cpu, memory, disk, network)
        """
        try:
            data = {}

            # 基础系统信息
            data["platform"] = platform.system()
            data["platform_version"] = platform.version()
            data["architecture"] = platform.machine()
            data["hostname"] = platform.node()
            data["python_version"] = platform.python_version()

            # 尝试获取详细资源信息
            try:
                import psutil

                if info_type in ["all", "cpu"]:
                    cpu = psutil.cpu_times()
                    data["cpu"] = {
                        "percent": psutil.cpu_percent(interval=1),
                        "count": psutil.cpu_count(),
                        "user_time": cpu.user,
                        "system_time": cpu.system
                    }

                if info_type in ["all", "memory"]:
                    memory = psutil.virtual_memory()
                    data["memory"] = {
                        "percent": memory.percent,
                        "total_gb": round(memory.total / (1024**3), 2),
                        "used_gb": round(memory.used / (1024**3), 2),
                        "available_gb": round(memory.available / (1024**3), 2)
                    }

                if info_type in ["all", "disk"]:
                    disk = psutil.disk_usage('/')
                    data["disk"] = {
                        "percent": disk.percent,
                        "total_gb": round(disk.total / (1024**3), 2),
                        "used_gb": round(disk.used / (1024**3), 2),
                        "free_gb": round(disk.free / (1024**3), 2)
                    }

                if info_type in ["all", "network"]:
                    net = psutil.net_io_counters()
                    data["network"] = {
                        "bytes_sent": net.bytes_sent,
                        "bytes_recv": net.bytes_recv,
                        "packets_sent": net.packets_sent,
                        "packets_recv": net.packets_recv
                    }

                # 进程信息
                if info_type in ["all", "processes"]:
                    data["processes"] = {
                        "count": len(psutil.pids()),
                        "running": len([p for p in psutil.pids() if psutil.pid_exists(p)])
                    }

            except ImportError:
                data["note"] = "安装 psutil 可获取更详细的系统信息: pip install psutil"

            return SkillResult(
                success=True,
                data=data
            )

        except Exception as e:
            return SkillResult(
                success=False,
                error=f"获取系统信息错误: {str(e)}"
            )

    async def get_process_list(self, **kwargs) -> SkillResult:
        """获取进程列表"""
        try:
            import psutil

            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
                try:
                    info = proc.info
                    processes.append({
                        "pid": info['pid'],
                        "name": info['name'],
                        "cpu": info.get('cpu_percent', 0),
                        "memory": info.get('memory_percent', 0)
                    })
                except Exception:
                    continue

            # 按 CPU 使用率排序
            processes.sort(key=lambda x: x['cpu'], reverse=True)

            return SkillResult(
                success=True,
                data={
                    "processes": processes[:50],  # 只返回前 50 个
                    "total": len(processes)
                }
            )

        except ImportError:
            return SkillResult(
                success=False,
                error="需要安装 psutil"
            )
        except Exception as e:
            return SkillResult(
                success=False,
                error=f"获取进程列表错误: {str(e)}"
            )
