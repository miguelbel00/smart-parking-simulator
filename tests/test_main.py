"""Composition and shutdown tests for the application entry point."""

from unittest.mock import Mock, call

import pytest

import main


def test_main_composes_modules_with_one_shared_queue(monkeypatch) -> None:
    queue = object()
    parking = Mock()
    simulator = Mock()
    app = Mock()
    app.run.side_effect = RuntimeError("window closed")
    lifecycle = Mock()
    lifecycle.attach_mock(simulator, "simulator")
    lifecycle.attach_mock(parking, "parking")

    monkeypatch.setattr(main, "Queue", Mock(return_value=queue))
    parking_factory = Mock(return_value=parking)
    simulator_factory = Mock(return_value=simulator)
    app_factory = Mock(return_value=app)
    monkeypatch.setattr(main, "ParkingLot", parking_factory)
    monkeypatch.setattr(main, "Simulator", simulator_factory)
    monkeypatch.setattr(main, "ParkingApp", app_factory)

    with pytest.raises(RuntimeError, match="window closed"):
        main.main()

    parking_factory.assert_called_once_with(
        capacity=main.PARKING_CAPACITY,
        event_queue=queue,
    )
    simulator_factory.assert_called_once_with(parking=parking, event_queue=queue)
    app_factory.assert_called_once_with(
        event_queue=queue,
        simulator=simulator,
        capacity=main.PARKING_CAPACITY,
    )
    app.run.assert_called_once_with()
    simulator.stop.assert_called_once_with()
    parking.close.assert_called_once_with(wait=True)
    assert lifecycle.mock_calls[-2:] == [
        call.simulator.stop(),
        call.parking.close(wait=True),
    ]
