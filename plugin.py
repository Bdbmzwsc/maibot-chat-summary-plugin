from typing import List, Tuple, Type

from src.common.logger import get_logger
from src.plugin_system import (
    BasePlugin,
    register_plugin,
    ComponentInfo,
    ConfigField
)
from .components.chat_summary_command import ChatSummaryCommand

logger = get_logger("chat_summary_plugin")


@register_plugin
class ChatSummaryPlugin(BasePlugin):
    # 插件基本信息
    plugin_name: str = "chat_summary_plugin"  # 内部标识符
    enable_plugin: bool = True
    dependencies: List[str] = []  # 插件依赖列表
    python_dependencies: List[str] = []  # Python包依赖列表
    config_file_name: str = "config.toml"  # 配置文件名
    config_section_descriptions = {
        # 插件基础配置
        "chat_summary_plugin": "聊天总结插件配置",
        # llm配置
        "llm_config": "LLM模型配置",
        # 权限设置
        "permissions": "权限设置，定义哪些用户可以使用插件功能",
    }  # 配置文件各节描述
    config_schema = {
        "chat_summary_plugin": {
            "max_message_count": ConfigField(
                type=int,
                default=700,
                description="生成总结时使用的最大消息记录条数。请注意性能消耗、token消耗和模型最大token限制！",
            ),
            "retrieval_message_count": ConfigField(
                type=int,
                default=30000,
                description="生成总结时检索的最大消息记录条数。用于从数据库中读取消息并从中筛选。请注意性能消耗",
            ),
            # 生成画像时的单条消息最大字数限制，超过这个字数的消息会被截断 0表示不限制
            "max_message_length": ConfigField(
                type=int,
                default=200,
                description="生成总结的单条消息最大字数限制，超过这个字数的消息会被截断。0表示不限制。",
            ),
            # 生成总结时使用的提示词
            # 支持变量：
            # 用户昵称:{person_name}
            # 用户QQ昵称:{user_nickname}
            # 消息数量 {message_count}
            # 消息内容 {messages}
            # 上文消息数量 {context_length}
            # 下文消息数量 {context_length_after}
            "prompt_template": ConfigField(
                type=str,
                input_type="textarea",
                default="# Role\n你是一个聊天总结ai。\n# Context\n**注意**：\n1. 聊天记录中的图片已被过滤，请忽略图片缺失带来的影响。\n\n# Task\n请基于提供的聊天记录，完成以下任务：对接下来的聊天记录生成一个聊天总结。\n\n# Input Data\n--- 聊天记录开始 ---\n{messages}\n--- 聊天记录结束 ---\n\n# Output Requirement\n",
                description="生成总结时使用的提示词 支持变量：消息数量 {message_count} 消息内容 {messages}",
            ),
        },
        "llm_config": {
            # 生成总结时使用的LLM模型分组
            "llm_group": ConfigField(
                type=str,
                choices=['lpmm_entity_extract', 'lpmm_rdf_build', 'planner', 'replyer', 'tool_use', 'utils', 'vlm'],
                default="utils",
                description="生成总结时使用的LLM模型分组 懒得设置的话在这选一个就能用。下面的设置对该处选择的模型不生效，从这选的模型在webui的“为模型分配功能”中设定。如果想详细配置请在下方手动配置",
            ),
            # 生成总结使用的模型名称 会优先使用该处设置，当此处为空时会使用LLM模型分组中指定的模型
            "llm_list": ConfigField(
                type=list,
                item_type="string",
                default=["gemini-2.5-pro", "glm-4.7", "LongCat-Flash-Thinking"],
                description="生成总结使用的模型名称(你在模型管理中添加的模型的名称)。当此处不为空时会使用此处设定的模型，否则使用LLM模型分组中指定的模型",
            ),
            # 生成总结时使用的模型的最大输出token数
            "max_tokens": ConfigField(
                type=int,
                default=20000,
                description="生成总结时使用的模型的最大输出token数，仅对手动设置的模型生效 请根据实际情况设置，避免超过模型限制",
            ),
            # 生成总结时使用的模型的温度
            "temperature": ConfigField(
                type=float,
                default=0.7,
                description="生成总结时使用的模型的温度，仅对手动设置的模型生效",
            ),
            # 生成总结时使用的模型的慢请求阈值 单位秒，超过该时间会输出警告日志
            "slow_threshold": ConfigField(
                type=float,
                default=30,
                description="生成总结时使用的模型的慢请求阈值，单位秒，超过该时间会输出警告日志。仅对手动设置的模型生效",
            ),
            # 生成总结时使用的模型的选择策略 balance（负载均衡）或 random（随机选择）
            "selection_strategy": ConfigField(
                type=str,
                choices=['balance', 'random'],
                default="balance",
                description="生成总结时使用的模型的选择策略，仅对手动设置的模型生效 balance（负载均衡）或 random（随机选择）",
            ),
        },
        "permissions": {
            # 管理员用户ID列表，能查看所有聊天流的画像
            "admin_id_list": ConfigField(
                type=list,
                item_type="string",
                default=["1234567890"],
                description="管理员用户ID列表，能查看所有聊天流的画像",
            ),
            # 权限模式，可选：白名单、黑名单。
            "permission_mode": ConfigField(
                type=str,
                choices=['whitelist', 'blacklist'],
                default="blacklist",
                description="权限模式，可选：白名单、黑名单。白名单模式下，只有在列表中的用户可以使用插件功能；黑名单模式下，除了在列表中的用户，其他用户都可以使用插件功能",
            ),
            # 用户ID列表，根据权限模式决定是允许还是禁止使用插件功能的用户列表
            "user_id_list": ConfigField(
                type=list,
                item_type="object",
                item_fields={
                    "user_id": {
                        "type": "string",
                        "label": "用户的QQ号",
                        "placeholder": "用户的QQ号"
                    },
                    "description": {
                        "type": "string",
                        "label": "描述",
                        "placeholder": "可选，对该用户的简短描述，仅便于查看，不会影响功能"
                    },
                },
                default=[{"user_id": "1234567890", "description": "示例用户"}],
                description="用户ID列表，根据权限模式决定是允许还是禁止使用插件功能的用户列表",
            ),
        }
    }

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        permission_mode: str = self.config.get("permissions", {}).get("permission_mode", "blacklist")
        user_id_list = self.config.get("permissions", {}).get("user_id_list", [])
        user_id_list = [item["user_id"] for item in user_id_list if "user_id" in item]
        admin_id_list = self.config.get("permissions", {}).get("admin_id_list", [])
        if permission_mode not in ["whitelist", "blacklist"]:
            logger.warning(f"权限模式设置为 {permission_mode}，但这不是一个有效的权限模式。请检查配置并设置为 'whitelist' 或 'blacklist'。默认将使用黑名单模式")
            permission_mode = "blacklist"
        if permission_mode == "whitelist" and not user_id_list:
            logger.warning("权限模式为白名单，但用户ID列表为空，这将导致没有用户可以使用插件功能！")
        ChatSummaryCommand.permission_mode = permission_mode
        ChatSummaryCommand.user_id_list = user_id_list
        ChatSummaryCommand.admin_id_list = admin_id_list
        return [
            (ChatSummaryCommand.get_command_info(), ChatSummaryCommand),
        ]
