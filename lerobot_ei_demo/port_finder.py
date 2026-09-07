import time


def _available_ports() -> list[str]:
    try:
        from serial.tools import list_ports
    except ImportError as error:
        raise RuntimeError(
            "pyserial is required to discover robot ports; reinstall the hardware extra"
        ) from error

    return sorted(port.device for port in list_ports.comports())


def main() -> None:
    print("Finding all available serial ports.")
    ports_before = _available_ports()
    print("Ports before disconnecting:", ports_before)
    input("Disconnect one arm, then press Enter: ")
    time.sleep(0.5)
    ports_after = _available_ports()
    ports_diff = sorted(set(ports_before) - set(ports_after))

    if len(ports_diff) == 1:
        print(f"The port of the disconnected arm is '{ports_diff[0]}'")
        print("Reconnect the arm.")
    elif not ports_diff:
        raise OSError(f"Could not detect the port. No difference was found ({ports_diff}).")
    else:
        raise OSError(
            f"Could not detect the port. More than one difference was found ({ports_diff})."
        )


if __name__ == "__main__":
    main()
