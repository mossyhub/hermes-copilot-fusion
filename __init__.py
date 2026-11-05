"""Standalone Copilot Fusion provider. Discovery performs no process launch."""
from providers import register_provider
from providers.base import ProviderProfile
from pathlib import Path


class FusionProfile(ProviderProfile):
    def discover_models(self, **kwargs):
        client = self.create_client(**kwargs)
        try:
            enabled = set(client.list_models(timeout_seconds=kwargs.get('timeout', 15.0)))
            return [{'id': model, 'label': label} for model, label in (
                ('fusion-standard', 'Fusion Standard'), ('fusion-high', 'Fusion High'),
                ('fusion-max', 'Fusion Max')) if model in enabled]
        finally:
            client.close()

    def fetch_models(self, **kwargs):
        return [row['id'] for row in self.discover_models(**kwargs)]

    def create_client(self, **kwargs):
        from .fusion.client import CopilotACPClient
        import os
        import shlex
        command = kwargs.pop('command', None) or os.getenv('HERMES_FUSION_BRIDGE') or self.process_command
        args = kwargs.pop('args', None)
        if args is None:
            raw = os.getenv(self.process_args_env_var, '')
            args = shlex.split(raw) if raw else list(self.process_args)
        return CopilotACPClient(command=command, args=args, **kwargs)


_local_bridge = Path(__file__).parent / 'bin' / 'weave-copilot'
_local_cli = _local_bridge.with_name('copilot')
profile = FusionProfile(
    name='copilot-fusion', display_name='Copilot Fusion',
    description='Fusion orchestration; Hermes owns all tools and approvals',
    auth_type='external_process', base_url='fusion://copilot',
    supports_streaming=True, supports_vision=True,
    supports_health_check=False, supports_model_listing=False,
    process_command=str(_local_bridge) if _local_bridge.is_file() else 'weave-copilot',
    process_args=('--copilot-cli', str(_local_cli) if _local_cli.is_file() else 'copilot', '--hydrafusion', '--hermes-tools-only'),
    process_command_env_vars=('HERMES_FUSION_BRIDGE',),
    process_args_env_var='HERMES_FUSION_ARGS',
)
register_provider(profile)
