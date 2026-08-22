# LumaFlow v1.0 (2026-08-07)
# Vérifie que les grands domaines du package lumaflow (engine, config, addons, persistence) sont
# tous importables sans erreur.


def test_domains_importable():
    import lumaflow.engine
    import lumaflow.config
    import lumaflow.addons
    import lumaflow.persistence
