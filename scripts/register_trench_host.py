"""Historical CLI alias; use register_host.py for new products."""
if __package__:
    from .register_host import main
else:
    from register_host import main

if __name__ == "__main__":
    raise SystemExit(main())
